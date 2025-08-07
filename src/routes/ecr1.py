# ecr.py (updated for production-ready ECR simulator)
import json
import time
import os
import binascii
import uuid
import threading
import serial
import socket
from base64 import b64encode
import logging
import requests

# Configure logging
logging.basicConfig(
    filename="ecr_simulator.log",
    level=logging.INFO,  # Set to INFO for production, DEBUG for dev
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)
from flask import Blueprint, request, jsonify, Response

ecr_bp = Blueprint("ecr", __name__)
# Define settings file path relative to the script
BASE_DIR = os.path.dirname(__file__)
SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")
# Load existing settings if available
app_settings = {}
if os.path.exists(SETTINGS_FILE):
    try:
        with open(SETTINGS_FILE, "r") as f:
            app_settings = json.load(f)
        logger.info(f"Settings loaded: {app_settings}")
    except json.JSONDecodeError:
        app_settings = {}  # Reset to empty dict if file is corrupted
        logger.error("JSONDecodeError loading settings file")
    except Exception as e:
        logger.error(f"Error loading settings file: {e}")
        app_settings = {}
else:
    logger.warning("Settings file not found, using defaults")
transaction_history = {}  # Changed to history, limited to last 5


def calculate_lrc(message_bytes):
    """Calculate Longitudinal Redundancy Check (LRC) as per spec."""
    lrc = 0
    for byte in message_bytes:
        lrc ^= byte
    return lrc


def build_native_request(trans_type_code, amount_pad, additional_fields={}):
    """Build Native request message with STX, length, data, ETX, and LRC."""
    trans_type_byte = bytes([int(trans_type_code, 16)])
    amount_bytes = amount_pad.encode("ascii")
    data_bytes = trans_type_byte + b"\x1c" + amount_bytes
    if "invoiceNo" in additional_fields:
        invoice_bytes = additional_fields["invoiceNo"].encode("ascii")
        data_bytes += b"\x1c" + invoice_bytes
    length_str = f"{len(data_bytes):04d}"
    length_bytes = length_str.encode("ascii")
    message = b"\x02" + length_bytes + data_bytes + b"\x03"
    lrc = calculate_lrc(message)
    message += bytes([lrc])
    return message


def parse_native_request(message_bytes):
    """Parse Native request to extract transType, amount, etc. for history."""
    if message_bytes[0] != 0x02:
        return None, "Invalid STX"
    length = int(message_bytes[1:5])
    data_bytes = message_bytes[5 : 5 + length]
    fields = data_bytes.split(b"\x1c")
    if len(fields) < 2:
        return None, "Invalid request format"
    trans_type = f"{int.from_bytes(fields[0], 'big'):02X}"
    amount = fields[1].decode("ascii")
    invoiceNo = fields[2].decode("ascii") if len(fields) > 2 else None
    return {
        "transType": trans_type,
        "transAmount": amount,
        "invoiceNo": invoiceNo,
    }, None


def parse_native_response(response_bytes):
    """Parse Native response message, validate STX, ETX, and LRC."""
    if not response_bytes or response_bytes[0] != 0x02:
        return None, "Invalid STX"
    if len(response_bytes) < 6:
        return None, "Message too short"
    length = int(response_bytes[1:5].decode("ascii"))
    if len(response_bytes) < 5 + length + 2:
        return None, "Incomplete message"
    if response_bytes[5 + length] != 0x03:
        return None, "Invalid ETX"
    calc_lrc = calculate_lrc(response_bytes[:-1])
    if calc_lrc != response_bytes[-1]:
        return None, "Invalid LRC"
    data_bytes = response_bytes[5 : 5 + length]
    fields_bytes = data_bytes.split(b"\x1c")
    return fields_bytes, None


def send_serial_message(serial_port, message, timeout=2):
    """Send message over serial and wait for ACK/NAK and response with timeout."""
    try:
        ser = serial.Serial(
            port=serial_port,
            baudrate=int(app_settings.get("speed_baud", 9600)),
            bytesize=int(app_settings.get("data_bits", 8)),
            stopbits=int(app_settings.get("stop_bits", 1)),
            parity=app_settings.get("parity", "N")[0].upper(),
            timeout=timeout,
        )
        ser.write(message)
        start_time = time.time()
        while time.time() - start_time < timeout:
            ack_nak = ser.read(1)
            if ack_nak:
                break
        if not ack_nak:
            ser.close()
            return None, "No ACK/NAK received within timeout"
        if ack_nak == b"\x15":
            ser.close()
            return None, "NAK received"
        if ack_nak != b"\x06":
            ser.close()
            return None, "Invalid ACK/NAK"
        response = b""
        start_time = time.time()
        while time.time() - start_time < timeout:
            byte = ser.read(1)
            if not byte:
                continue
            response += byte
            if byte == b"\x03":
                response += ser.read(1)  # LRC
                break
        if not response or b"\x03" not in response:
            ser.close()
            return None, "Incomplete response within timeout"
        ser.write(b"\x06")
        ser.close()
        return response, None
    except Exception as e:
        logger.error(f"Serial communication error: {str(e)}")
        return None, f"Serial communication error: {str(e)}"


def send_socket_message(ip, port, message, ssl_enabled=False):
    """Send message over socket and wait for response with timeout."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        if ssl_enabled:
            import ssl

            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            sock = context.wrap_socket(sock)
        sock.connect((ip, port))
        sock.send(message)
        start_time = time.time()
        ack_nak = b""
        while time.time() - start_time < 2:
            try:
                ack_nak = sock.recv(1)
                if ack_nak:
                    break
            except OSError:
                pass
        if not ack_nak:
            sock.close()
            return None, "No ACK/NAK received within timeout"
        if ack_nak == b"\x15":
            sock.close()
            return None, "NAK received"
        if ack_nak != b"\x06":
            sock.close()
            return None, "Invalid ACK/NAK"
        response = b""
        start_time = time.time()
        while time.time() - start_time < 2:
            try:
                byte = sock.recv(1)
                if not byte:
                    continue
                response += byte
                if byte == b"\x03":
                    response += sock.recv(1)  # LRC
                    break
            except OSError:
                pass
        if not response or b"\x03" not in response:
            sock.close()
            return None, "Incomplete response within timeout"
        sock.send(b"\x06")
        sock.close()
        return response, None
    except Exception as e:
        logger.error(f"Socket communication error: {str(e)}")
        return None, f"Socket communication error: {str(e)}"


@ecr_bp.route("/build_request", methods=["POST"])
def build_request():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON data provided"}), 400
    transaction_type = data.get("transaction_type", "SALE")
    amount = data.get("amount", "0.00")
    invoice_no = data.get("invoiceNo", None)
    trans_type_map = {
        "SALE": "01",
        "INSTALLMENT": "02",
        "VOID": "03",
        "REFUND": "04",
        "QRIS MPM": "05",
        "QRIS NOTIFICATION": "06",
        "QRIS REFUND": "07",
        "POINT REWARD": "08",
        "TEST HOST": "09",
        "QRIS CPM": "0A",
        "SETTLEMENT": "0B",
        "REPRINT": "0C",
        "REPORT": "0D",
        "LOGON": "0E",
    }
    trans_code = trans_type_map.get(transaction_type.upper(), "01")
    amount_pad = f"{int(float(amount) * 100):012d}"
    additional = {}
    if (
        transaction_type.upper() in ["VOID", "REFUND", "REPRINT", "QRIS REFUND"]
        and invoice_no
    ):
        additional["invoiceNo"] = f"{int(invoice_no):06d}"
    if app_settings.get("enable_rest_api", False):
        req = {"transType": trans_code, "transAmount": amount_pad}
        if "invoiceNo" in additional:
            req["invoiceNo"] = additional["invoiceNo"]
        return jsonify({"request": json.dumps(req), "type": "json"})
    else:
        req_bytes = build_native_request(trans_code, amount_pad, additional)
        return jsonify(
            {
                "request": binascii.hexlify(req_bytes).upper().decode("ascii"),
                "type": "hex",
            }
        )


@ecr_bp.route("/native/process", methods=["POST"])
def native_process():
    data = request.get_json()
    message_hex = data.get("message_hex")
    try:
        if not message_hex or not isinstance(message_hex, str):
            logger.error("Invalid or missing message_hex")
            return jsonify({"error": "Invalid or missing message_hex"}), 400
        if not all(c in "0123456789ABCDEFabcdef" for c in message_hex):
            logger.error(f"Invalid hexadecimal string: {message_hex}")
            return jsonify({"error": "Invalid hexadecimal string"}), 400
        message_bytes = binascii.unhexlify(message_hex)
        if message_bytes[0] != 0x02:
            logger.error(f"Invalid STX in message: {message_hex}")
            return jsonify({"error": "Invalid STX"}), 400
        # Parse request for history
        req_parsed, parse_err = parse_native_request(message_bytes)
        if parse_err:
            return jsonify({"error": parse_err}), 400
        trx_id = uuid.uuid4().hex[:8].upper()
        transaction_history[trx_id] = {
            "status": "processing",
            "request": req_parsed,
            "timestamp": time.time(),
        }
        communication_type = app_settings.get("communication", "Serial")
        logger.info(f"Using communication type: {communication_type}")
        error = None
        response_bytes = None
        if communication_type == "Serial":
            serial_port = app_settings.get("serial_port", "")
            if not serial_port:
                logger.error("No serial port specified in settings")
                return jsonify({"error": "No serial port specified in settings"}), 400
            logger.info(f"Attempting serial communication on port: {serial_port}")
            response_bytes, error = send_serial_message(serial_port, message_bytes)
        else:
            socket_ip = app_settings.get("socket_ip", "127.0.0.1")
            socket_port = int(app_settings.get("socket_port", 9001))
            ssl_enabled = app_settings.get("enable_ssl", False)
            logger.info(
                f"Attempting socket communication to {socket_ip}:{socket_port}, SSL: {ssl_enabled}"
            )
            response_bytes, error = send_socket_message(
                socket_ip, socket_port, message_bytes, ssl_enabled
            )
        if error:
            logger.error(f"Communication error: {error}")
            transaction_history[trx_id]["status"] = "error"
            transaction_history[trx_id]["error"] = error
            return jsonify({"error": error}), 500
        fields_bytes, parse_error = parse_native_response(response_bytes)
        if parse_error:
            logger.error(f"Parse error: {parse_error}")
            transaction_history[trx_id]["status"] = "error"
            transaction_history[trx_id]["error"] = parse_error
            return jsonify({"error": parse_error}), 400
        # Parse response fields
        fields_str = [f.decode("ascii", errors="ignore") for f in fields_bytes]
        response_data = {
            "responseCode": fields_str[0] if len(fields_str) > 0 else "",
            "approvalCode": fields_str[1] if len(fields_str) > 1 else "",
            "date": fields_str[2] if len(fields_str) > 2 else "",
            "time": fields_str[3] if len(fields_str) > 3 else "",
            "tid": fields_str[4] if len(fields_str) > 4 else "",
            "mid": fields_str[5] if len(fields_str) > 5 else "",
            "invoiceNo": fields_str[6] if len(fields_str) > 6 else "",
            "batchNo": fields_str[7] if len(fields_str) > 7 else "",
            "traceNo": fields_str[8] if len(fields_str) > 8 else "",
            "cardType": fields_str[9] if len(fields_str) > 9 else "",
            "cardNo": fields_str[10] if len(fields_str) > 10 else "",
            "expDate": fields_str[11] if len(fields_str) > 11 else "",
            "cardholderName": fields_str[12] if len(fields_str) > 12 else "",
            "refNumber": fields_str[13] if len(fields_str) > 13 else "",
            "transAmount": (
                fields_str[14] if len(fields_str) > 14 else req_parsed["transAmount"]
            ),
            "transAddAmount": (
                fields_str[15] if len(fields_str) > 15 else "000000000000"
            ),
            "totalAmount": (
                fields_str[16] if len(fields_str) > 16 else req_parsed["transAmount"]
            ),
            "entryMode": fields_str[17] if len(fields_str) > 17 else "",
            "term": fields_str[18] if len(fields_str) > 18 else "00",
            "monthlyAmount": fields_str[19] if len(fields_str) > 19 else "000000000000",
            "pointReward": fields_str[20] if len(fields_str) > 20 else "000000",
            "redemptionAmount": (
                fields_str[21] if len(fields_str) > 21 else "000000000000"
            ),
            "pointBalance": fields_str[22] if len(fields_str) > 22 else "000000",
            "filler": fields_str[23] if len(fields_str) > 23 else "",
            "referenceId": fields_str[24] if len(fields_str) > 24 else "",
        }
        transaction_history[trx_id]["status"] = "done"
        transaction_history[trx_id]["response"] = response_data
        # Limit history to 5
        if len(transaction_history) > 5:
            oldest = min(
                transaction_history, key=lambda k: transaction_history[k]["timestamp"]
            )
            del transaction_history[oldest]
        response_hex = binascii.hexlify(response_bytes).upper().decode("ascii")
        return (
            jsonify(
                {
                    "response_hex": response_hex,
                    "response_json": response_data,
                    "trxId": trx_id,
                    "type": "hex",
                }
            ),
            200,
        )
    except binascii.Error as e:
        logger.error(f"Hex decoding error: {str(e)} - Message: {message_hex}")
        return jsonify({"error": f"Hex decoding error: {str(e)}"}), 400
    except serial.SerialException as e:
        logger.error(f"Serial communication error: {str(e)}")
        return jsonify({"error": f"Serial communication error: {str(e)}"}), 500
    except socket.error as e:
        logger.error(f"Socket communication error: {str(e)}")
        return jsonify({"error": f"Socket communication error: {str(e)}"}), 500
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500


@ecr_bp.route("/perform_rest", methods=["POST"])
def perform_rest():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400
    sn = app_settings.get("edc_serial_number", "")
    username = "VBF4C1MB"
    password = f"VFI{sn}"
    ip = app_settings.get("socket_ip", "127.0.0.1")
    port = app_settings.get("socket_port", 9001)
    protocol = "https" if app_settings.get("enable_ssl", False) else "http"
    verify = (
        False if app_settings.get("enable_ssl", False) else True
    )  # Ignore self-signed cert
    trx_url = f"{protocol}://{ip}:{port}/transaction/cimb"
    try:
        res = requests.post(
            trx_url, json=data, auth=(username, password), verify=verify, timeout=10
        )
        if res.status_code != 200:
            logger.error(f"Transaction request failed: {res.status_code} - {res.text}")
            return jsonify({"error": res.text}), res.status_code
        trx_data = res.json()
        trx_id = trx_data["trxId"]
    except requests.exceptions.RequestException as e:
        logger.error(f"Transaction request error: {str(e)}")
        return jsonify({"error": str(e)}), 500
    transaction_history[trx_id] = {
        "status": "processing",
        "request": data,
        "timestamp": time.time(),
    }
    result_url = f"{protocol}://{ip}:{port}/result/cimb"
    start_time = time.time()
    while time.time() - start_time < 60:  # 60s timeout
        try:
            res = requests.post(
                result_url,
                json={"trxId": trx_id},
                auth=(username, password),
                verify=verify,
                timeout=10,
            )
            if res.status_code == 503:
                time.sleep(1)
                continue
            if res.status_code != 200:
                logger.error(f"Result request failed: {res.status_code} - {res.text}")
                transaction_history[trx_id]["status"] = "error"
                transaction_history[trx_id]["error"] = res.text
                return jsonify({"error": res.text}), res.status_code
            result = res.json()
            transaction_history[trx_id]["status"] = "done"
            transaction_history[trx_id]["response"] = result
            # Limit history to 5
            if len(transaction_history) > 5:
                oldest = min(
                    transaction_history,
                    key=lambda k: transaction_history[k]["timestamp"],
                )
                del transaction_history[oldest]
            return jsonify(result), 200
        except requests.exceptions.RequestException as e:
            logger.error(f"Result polling error: {str(e)}")
            transaction_history[trx_id]["status"] = "error"
            transaction_history[trx_id]["error"] = str(e)
            return jsonify({"error": str(e)}), 500
    transaction_history[trx_id]["status"] = "error"
    transaction_history[trx_id]["error"] = "Polling timeout"
    return jsonify({"error": "Polling timeout"}), 408


@ecr_bp.route("/settings", methods=["GET", "POST"])
def manage_settings():
    global app_settings
    if request.method == "GET":
        default_settings = {
            "communication": "Serial",
            "serial_port": "",
            "socket_ip": "127.0.0.1",
            "socket_port": "9001",
            "speed_baud": "9600",
            "data_bits": "8",
            "stop_bits": "1",
            "parity": "None",
            "enable_rest_api": False,
            "enable_ssl": False,
            "edc_serial_number": "",
        }
        return jsonify(app_settings or default_settings)
    elif request.method == "POST":
        try:
            new_settings = request.get_json()
            if not isinstance(new_settings, dict):
                return (
                    jsonify({"status": "Error", "message": "Invalid settings format"}),
                    400,
                )
            # Validate and sanitize settings
            app_settings.update(
                {
                    "communication": new_settings.get("communication", "Serial"),
                    "serial_port": str(new_settings.get("serial_port", "")),
                    "socket_ip": str(new_settings.get("socket_ip", "127.0.0.1")),
                    "socket_port": str(new_settings.get("socket_port", "9001")),
                    "speed_baud": str(new_settings.get("speed_baud", "9600")),
                    "data_bits": str(new_settings.get("data_bits", "8")),
                    "stop_bits": str(new_settings.get("stop_bits", "1")),
                    "parity": str(new_settings.get("parity", "None")),
                    "enable_rest_api": bool(new_settings.get("enable_rest_api", False)),
                    "enable_ssl": bool(new_settings.get("enable_ssl", False)),
                    "edc_serial_number": str(new_settings.get("edc_serial_number", "")),
                }
            )
            # Save to file with error handling
            with open(SETTINGS_FILE, "w") as f:
                json.dump(app_settings, f, indent=4)
            return jsonify(
                {"status": "Settings saved successfully", "settings": app_settings}
            )
        except Exception as e:
            logger.error(f"Settings save error: {str(e)}", exc_info=True)
            return (
                jsonify(
                    {"status": "Error", "message": f"Failed to save settings: {str(e)}"}
                ),
                500,
            )


@ecr_bp.route("/status", methods=["GET"])
def get_status():
    return jsonify(
        {
            "status": "ONLINE",
            "version": "V4.2",
            "uptime": time.time(),
            "last_transaction": None,
        }
    )


@ecr_bp.route("/connect", methods=["POST"])
def test_connection():
    data = request.get_json()
    settings = data.get("settings", {})
    communication_type = settings.get("communication", "Serial")
    if communication_type == "Serial":
        serial_port = settings.get("serial_port", "")
        if not serial_port:
            return (
                jsonify({"connected": False, "error": "No serial port specified"}),
                400,
            )
        try:
            ser = serial.Serial(
                port=serial_port,
                baudrate=int(settings.get("speed_baud", 9600)),
                bytesize=int(settings.get("data_bits", 8)),
                stopbits=int(settings.get("stop_bits", 1)),
                parity=settings.get("parity", "N")[0].upper(),
                timeout=2,
            )
            ser.close()
            return jsonify(
                {"connected": True, "message": "Serial connection successful"}
            )
        except Exception as e:
            logger.error(f"Serial connection test error: {str(e)}")
            return (
                jsonify(
                    {"connected": False, "error": f"Serial connection failed: {str(e)}"}
                ),
                400,
            )
    elif communication_type == "Socket":
        socket_ip = settings.get("socket_ip", "127.0.0.1")
        socket_port = int(settings.get("socket_port", 9001))
        ssl_enabled = settings.get("enable_ssl", False)
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            if ssl_enabled:
                import ssl

                context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                sock = context.wrap_socket(sock)
            sock.connect((socket_ip, socket_port))
            sock.close()
            return jsonify(
                {"connected": True, "message": "Socket connection successful"}
            )
        except Exception as e:
            logger.error(f"Socket connection test error: {str(e)}")
            return (
                jsonify(
                    {"connected": False, "error": f"Socket connection failed: {str(e)}"}
                ),
                400,
            )
    return jsonify({"connected": False, "error": "Invalid communication type"}), 400


@ecr_bp.route("/history", methods=["GET"])
def get_history():
    trans_type_map = {
        "01": "SALE",
        "02": "INSTALLMENT",
        "03": "VOID",
        "04": "REFUND",
        "05": "QRIS MPM",
        "06": "QRIS NOTIFICATION",
        "07": "QRIS REFUND",
        "08": "POINT REWARD",
        "09": "TEST HOST",
        "0A": "QRIS CPM",
        "0B": "SETTLEMENT",
        "0C": "REPRINT",
        "0D": "REPORT",
        "0E": "LOGON",
    }
    history = [
        {
            "id": k,
            "timestamp": v["timestamp"],
            "transaction_type": trans_type_map.get(
                v["request"]["transType"], "UNKNOWN"
            ),
            "amount": str(int(v["request"]["transAmount"]) / 100),
            "status": v["status"].upper(),
            "transaction_id": k,
        }
        for k, v in sorted(
            transaction_history.items(), key=lambda x: x[1]["timestamp"], reverse=True
        )
    ]
    return jsonify(history)

import json
import time
import os
import binascii
import uuid
import threading
import serial
import socket
import struct
from base64 import b64encode
import logging
import requests

# Configure logging
logging.basicConfig(
    filename="ecr_simulator.log",
    level=logging.INFO,
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
        app_settings = {}
        logger.error("JSONDecodeError loading settings file")
    except Exception as e:
        logger.error(f"Error loading settings file: {e}")
        app_settings = {}
else:
    logger.warning("Settings file not found, using defaults")

transaction_history = {}
is_connected = False
connected_socket = None  # For maintaining a persistent socket connection, if needed


# ReqData structure based on documentation
class ReqData:
    def __init__(self):
        self.chTransType = 0x00  # 1 byte - Transaction type
        self.szAmount = b"000000000000"  # 12 bytes - Transaction amount
        self.szInvNo = b"000000"  # 6 bytes - Invoice number
        self.szCardNo = b"\x00" * 19  # 19 bytes - Card number

    def pack(self):
        """Pack ReqData structure into bytes according to documentation format."""
        packed = struct.pack("B", self.chTransType)  # 1 byte
        packed += self.szAmount[:12].ljust(12, b"\x00")  # 12 bytes
        packed += self.szInvNo[:6].ljust(6, b"\x00")  # 6 bytes
        packed += self.szCardNo[:19].ljust(19, b"\x00")  # 19 bytes
        return packed


# RspData structure based on documentation
class RspData:
    def __init__(self):
        self.chTransType = 0x00  # 1 byte - Transaction type
        self.szTID = b"\x00" * 8  # 8 bytes - Terminal ID
        self.szMID = b"\x00" * 15  # 15 bytes - Merchant ID
        self.szTraceNo = b"\x00" * 6  # 6 bytes - Trace number
        self.szInvoiceNo = b"\x00" * 6  # 6 bytes - Invoice number
        self.chEntryMode = 0x00  # 1 byte - Entry mode
        self.szTransAmount = b"\x00" * 12  # 12 bytes - Transaction amount
        self.szTransAddAmount = b"\x00" * 12  # 12 bytes - Additional amount
        self.szTotalAmount = b"\x00" * 12  # 12 bytes - Total amount
        self.szCardNo = b"\x00" * 19  # 19 bytes - Card number
        self.szCardholderName = b"\x00" * 26  # 26 bytes - Cardholder name
        self.szDate = b"\x00" * 8  # 8 bytes - Date (YYYYMMDD)
        self.szTime = b"\x00" * 6  # 6 bytes - Time (HHMMSS)
        self.szApprovalCode = b"\x00" * 6  # 6 bytes - Approval code
        self.szResponseCode = b"\x00" * 2  # 2 bytes - Response code
        self.szRefNumber = b"\x00" * 12  # 12 bytes - Reference number
        self.szReferenceId = b"\x00" * 6  # 6 bytes - Reference ID
        self.szTerm = b"\x00" * 2  # 2 bytes - Term
        self.szMonthlyAmount = b"\x00" * 12  # 12 bytes - Monthly amount
        self.szPointReward = b"\x00" * 9  # 9 bytes - Point reward
        self.szRedemptionAmount = b"\x00" * 11  # 11 bytes - Redemption amount
        self.szPointBalance = b"\x00" * 9  # 9 bytes - Point balance
        self.szFiller = b"\x00" * 99  # 99 bytes - Filler

    @classmethod
    def unpack(cls, data):
        """Unpack bytes into RspData structure according to documentation format."""
        rsp = cls()
        offset = 0
        rsp.chTransType = struct.unpack_from("B", data, offset)[0]
        offset += 1
        rsp.szTID = data[offset : offset + 8]
        offset += 8
        rsp.szMID = data[offset : offset + 15]
        offset += 15
        rsp.szTraceNo = data[offset : offset + 6]
        offset += 6
        rsp.szInvoiceNo = data[offset : offset + 6]
        offset += 6
        rsp.chEntryMode = struct.unpack_from("B", data, offset)[0]
        offset += 1
        rsp.szTransAmount = data[offset : offset + 12]
        offset += 12
        rsp.szTransAddAmount = data[offset : offset + 12]
        offset += 12
        rsp.szTotalAmount = data[offset : offset + 12]
        offset += 12
        rsp.szCardNo = data[offset : offset + 19]
        offset += 19
        rsp.szCardholderName = data[offset : offset + 26]
        offset += 26
        rsp.szDate = data[offset : offset + 8]
        offset += 8
        rsp.szTime = data[offset : offset + 6]
        offset += 6
        rsp.szApprovalCode = data[offset : offset + 6]
        offset += 6
        rsp.szResponseCode = data[offset : offset + 2]
        offset += 2
        rsp.szRefNumber = data[offset : offset + 12]
        offset += 12
        rsp.szReferenceId = data[offset : offset + 6]
        offset += 6
        rsp.szTerm = data[offset : offset + 2]
        offset += 2
        rsp.szMonthlyAmount = data[offset : offset + 12]
        offset += 12
        rsp.szPointReward = data[offset : offset + 9]
        offset += 9
        rsp.szRedemptionAmount = data[offset : offset + 11]
        offset += 11
        rsp.szPointBalance = data[offset : offset + 9]
        offset += 9
        if offset < len(data):
            rsp.szFiller = data[offset : offset + 99]
        return rsp

    def to_dict(self):
        """Convert RspData to dictionary for JSON response."""
        return {
            "transType": f"{self.chTransType:02X}",
            "tid": self.szTID.rstrip(b"\x00").decode("ascii", errors="ignore"),
            "mid": self.szMID.rstrip(b"\x00").decode("ascii", errors="ignore"),
            "traceNo": self.szTraceNo.rstrip(b"\x00").decode("ascii", errors="ignore"),
            "invoiceNo": self.szInvoiceNo.rstrip(b"\x00").decode(
                "ascii", errors="ignore"
            ),
            "entryMode": f"{self.chEntryMode:02X}",
            "transAmount": self.szTransAmount.rstrip(b"\x00").decode(
                "ascii", errors="ignore"
            ),
            "transAddAmount": self.szTransAddAmount.rstrip(b"\x00").decode(
                "ascii", errors="ignore"
            ),
            "totalAmount": self.szTotalAmount.rstrip(b"\x00").decode(
                "ascii", errors="ignore"
            ),
            "cardNo": self.szCardNo.rstrip(b"\x00").decode("ascii", errors="ignore"),
            "cardholderName": self.szCardholderName.rstrip(b"\x00").decode(
                "ascii", errors="ignore"
            ),
            "date": self.szDate.rstrip(b"\x00").decode("ascii", errors="ignore"),
            "time": self.szTime.rstrip(b"\x00").decode("ascii", errors="ignore"),
            "approvalCode": self.szApprovalCode.rstrip(b"\x00").decode(
                "ascii", errors="ignore"
            ),
            "responseCode": self.szResponseCode.rstrip(b"\x00").decode(
                "ascii", errors="ignore"
            ),
            "refNumber": self.szRefNumber.rstrip(b"\x00").decode(
                "ascii", errors="ignore"
            ),
            "referenceId": self.szReferenceId.rstrip(b"\x00").decode(
                "ascii", errors="ignore"
            ),
            "term": self.szTerm.rstrip(b"\x00").decode("ascii", errors="ignore"),
            "monthlyAmount": self.szMonthlyAmount.rstrip(b"\x00").decode(
                "ascii", errors="ignore"
            ),
            "pointReward": self.szPointReward.rstrip(b"\x00").decode(
                "ascii", errors="ignore"
            ),
            "redemptionAmount": self.szRedemptionAmount.rstrip(b"\x00").decode(
                "ascii", errors="ignore"
            ),
            "pointBalance": self.szPointBalance.rstrip(b"\x00").decode(
                "ascii", errors="ignore"
            ),
        }


def pack_request_msg(trans_type, amount, invoice_no, card_no=""):
    """Pack request message following CimbEcrLibrary.java example."""
    req_data = ReqData()
    req_data.chTransType = int(trans_type, 16)
    amount_str = f"{int(float(amount) * 100):010d}00"
    req_data.szAmount = amount_str.encode("ascii")[:12]
    if invoice_no:
        inv_str = f"{int(invoice_no):06d}"
        req_data.szInvNo = inv_str.encode("ascii")[:6]
    if card_no:
        req_data.szCardNo = card_no.encode("ascii")[:19]
    return req_data.pack()


def parse_response_msg(response_bytes):
    """Parse response message following CimbEcrLibrary.java example."""
    try:
        rsp_data = RspData.unpack(response_bytes)
        return rsp_data, None
    except Exception as e:
        logger.error(f"Error parsing response: {str(e)}")
        return None, f"Error parsing response: {str(e)}"


def send_serial_message(serial_port, message, timeout=10):
    """Send message over serial port following ECR communication protocol."""
    try:
        ser = serial.Serial(
            port=serial_port,
            baudrate=int(app_settings.get("speed_baud", 9600)),
            bytesize=int(app_settings.get("data_bits", 8)),
            stopbits=int(app_settings.get("stop_bits", 1)),
            parity=app_settings.get("parity", "N")[0].upper(),
            timeout=timeout,
        )
        logger.info(
            f"Sending message over serial: {binascii.hexlify(message).decode()}"
        )
        ser.write(message)
        response = ser.read(1024)
        logger.info(f"Received response: {binascii.hexlify(response).decode()}")
        ser.close()
        return response, None
    except Exception as e:
        logger.error(f"Serial communication error: {str(e)}")
        return None, f"Serial communication error: {str(e)}"


def send_socket_message(ip, port, message, ssl_enabled=False, timeout=10):
    """Send message over socket following ECR communication protocol."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        if ssl_enabled:
            import ssl

            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            sock = context.wrap_socket(sock)
        logger.info(f"Connecting to {ip}:{port}")
        sock.connect((ip, port))
        logger.info(
            f"Sending message over socket: {binascii.hexlify(message).decode()}"
        )
        sock.send(message)
        response = sock.recv(1024)
        logger.info(f"Received response: {binascii.hexlify(response).decode()}")
        sock.close()
        return response, None
    except Exception as e:
        logger.error(f"Socket communication error: {str(e)}")
        return None, f"Socket communication error: {str(e)}"


@ecr_bp.route("/build_request", methods=["POST"])
def build_request():
    """Build request message according to documentation format."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON data provided"}), 400
    transaction_type = data.get("transaction_type", "SALE")
    amount = data.get("amount", "0.00")
    invoice_no = data.get("invoiceNo", None)
    card_no = data.get("cardNo", "")
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
    try:
        req_bytes = pack_request_msg(trans_code, amount, invoice_no, card_no)
        return jsonify(
            {
                "request": binascii.hexlify(req_bytes).upper().decode("ascii"),
                "type": "hex",
                "structure": "ReqData",
            }
        )
    except Exception as e:
        logger.error(f"Error building request: {str(e)}")
        return jsonify({"error": f"Error building request: {str(e)}"}), 500


@ecr_bp.route("/process", methods=["POST"])
def process_transaction():
    """Process transaction following CimbEcrLibrary communication flow."""
    global is_connected, connected_socket
    if not is_connected:
        return jsonify({"error": "Not connected to ECR device"}), 400

    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON data provided"}), 400

    transaction_type = data.get("transaction_type", "SALE")
    amount = data.get("amount", "0.00")
    invoice_no = data.get("invoiceNo", None)
    card_no = data.get("cardNo", "")

    try:
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
        req_bytes = pack_request_msg(trans_code, amount, invoice_no, card_no)

        trx_id = uuid.uuid4().hex[:8].upper()
        transaction_history[trx_id] = {
            "status": "processing",
            "request": {
                "transType": trans_code,
                "amount": amount,
                "invoiceNo": invoice_no,
                "cardNo": card_no,
            },
            "timestamp": time.time(),
        }

        communication_type = app_settings.get("communication", "Serial")
        logger.info(f"Using communication type: {communication_type}")
        response_bytes = None
        error = None

        if communication_type == "Serial":
            serial_port = app_settings.get("serial_port", "")
            if not serial_port:
                error = "No serial port specified in settings"
            else:
                response_bytes, error = send_serial_message(serial_port, req_bytes)
        else:
            if connected_socket:
                logger.info(
                    f"Sending message over existing socket: {binascii.hexlify(req_bytes).decode()}"
                )
                connected_socket.send(req_bytes)
                response_bytes = connected_socket.recv(1024)
                logger.info(
                    f"Received response: {binascii.hexlify(response_bytes).decode()}"
                )
            else:
                socket_ip = app_settings.get("socket_ip", "127.0.0.1")
                socket_port = int(app_settings.get("socket_port", 9001))
                ssl_enabled = app_settings.get("enable_ssl", False)
                response_bytes, error = send_socket_message(
                    socket_ip, socket_port, req_bytes, ssl_enabled
                )

        if error:
            logger.error(f"Communication error: {error}")
            transaction_history[trx_id]["status"] = "error"
            transaction_history[trx_id]["error"] = error
            return jsonify({"error": error}), 500

        rsp_data, parse_error = parse_response_msg(response_bytes)
        if parse_error:
            logger.error(f"Parse error: {parse_error}")
            transaction_history[trx_id]["status"] = "error"
            transaction_history[trx_id]["error"] = parse_error
            return jsonify({"error": parse_error}), 400

        response_json = rsp_data.to_dict()
        transaction_history[trx_id]["status"] = "completed"
        transaction_history[trx_id]["response"] = response_json

        if len(transaction_history) > 5:
            oldest = min(
                transaction_history, key=lambda k: transaction_history[k]["timestamp"]
            )
            del transaction_history[oldest]

        return (
            jsonify(
                {
                    "trxId": trx_id,
                    "response_hex": binascii.hexlify(response_bytes)
                    .upper()
                    .decode("ascii"),
                    "response_json": response_json,
                    "type": "ReqData/RspData",
                }
            ),
            200,
        )
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500


@ecr_bp.route("/settings", methods=["GET", "POST"])
def settings():
    """Handle ECR settings."""
    global app_settings
    if request.method == "GET":
        return jsonify(app_settings)
    elif request.method == "POST":
        data = request.get_json()
        if data:
            app_settings.update(data)
            try:
                with open(SETTINGS_FILE, "w") as f:
                    json.dump(app_settings, f, indent=2)
                logger.info(f"Settings updated: {app_settings}")
                return jsonify({"message": "Settings updated successfully"})
            except Exception as e:
                logger.error(f"Error saving settings: {e}")
                return jsonify({"error": f"Error saving settings: {e}"}), 500
        else:
            return jsonify({"error": "No data provided"}), 400


@ecr_bp.route("/history", methods=["GET"])
def get_history():
    """Get transaction history."""
    return jsonify(transaction_history)


@ecr_bp.route("/test_connection", methods=["POST"])
def test_connection():
    """Test connection to ECR adaptor."""
    communication_type = app_settings.get("communication", "Serial")
    try:
        if communication_type == "Serial":
            serial_port = app_settings.get("serial_port", "")
            if not serial_port:
                return jsonify({"error": "No serial port specified"}), 400
            ser = serial.Serial(
                port=serial_port,
                baudrate=int(app_settings.get("speed_baud", 9600)),
                bytesize=int(app_settings.get("data_bits", 8)),
                stopbits=int(app_settings.get("stop_bits", 1)),
                parity=app_settings.get("parity", "N")[0].upper(),
                timeout=2,
            )
            ser.close()
            return jsonify(
                {"message": f"Serial connection to {serial_port} successful"}
            )
        else:
            socket_ip = app_settings.get("socket_ip", "127.0.0.1")
            socket_port = int(app_settings.get("socket_port", 9001))
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((socket_ip, socket_port))
            sock.close()
            return jsonify(
                {
                    "message": f"Socket connection to {socket_ip}:{socket_port} successful"
                }
            )
    except Exception as e:
        logger.error(f"Connection test failed: {str(e)}")
        return jsonify({"error": f"Connection test failed: {str(e)}"}), 500


@ecr_bp.route("/connect", methods=["POST"])
def connect_ecr():
    """Connect to or disconnect from the ECR device."""
    global is_connected, connected_socket
    data = request.get_json() or {}
    action = data.get("action", "connect")

    if action == "disconnect":
        try:
            if connected_socket:
                connected_socket.close()
                connected_socket = None
            is_connected = False
            logger.info("Disconnected from ECR device")
            return (
                jsonify(
                    {
                        "connected": False,
                        "message": "Successfully disconnected from ECR device",
                    }
                ),
                200,
            )
        except Exception as e:
            logger.error(f"Error disconnecting from ECR: {str(e)}")
            return (
                jsonify(
                    {"connected": False, "error": f"Failed to disconnect: {str(e)}"}
                ),
                500,
            )

    if is_connected:
        return (
            jsonify({"connected": True, "message": "Already connected to ECR device"}),
            200,
        )

    communication_type = app_settings.get("communication", "Serial")
    try:
        if communication_type == "Serial":
            serial_port = app_settings.get("serial_port", "")
            if not serial_port:
                logger.error("No serial port specified")
                return (
                    jsonify({"connected": False, "error": "No serial port specified"}),
                    400,
                )
            ser = serial.Serial(
                port=serial_port,
                baudrate=int(app_settings.get("speed_baud", 9600)),
                bytesize=int(app_settings.get("data_bits", 8)),
                stopbits=int(app_settings.get("stop_bits", 1)),
                parity=app_settings.get("parity", "N")[0].upper(),
                timeout=2,
            )
            ser.close()
            is_connected = True
            logger.info(f"Serial connection to {serial_port} successful")
            return (
                jsonify(
                    {
                        "connected": True,
                        "message": f"Serial connection to {serial_port} successful",
                    }
                ),
                200,
            )
        else:
            socket_ip = app_settings.get("socket_ip", "127.0.0.1")
            socket_port = int(app_settings.get("socket_port", 9001))
            ssl_enabled = app_settings.get("enable_ssl", False)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            if ssl_enabled:
                import ssl

                context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                sock = context.wrap_socket(sock)
            sock.connect((socket_ip, socket_port))
            connected_socket = sock
            is_connected = True
            logger.info(f"Socket connection to {socket_ip}:{socket_port} successful")
            return (
                jsonify(
                    {
                        "connected": True,
                        "message": f"Socket connection to {socket_ip}:{socket_port} successful",
                    }
                ),
                200,
            )
    except Exception as e:
        logger.error(f"Connection failed: {str(e)}")
        if connected_socket:
            connected_socket.close()
            connected_socket = None
        is_connected = False
        return (
            jsonify({"connected": False, "error": f"Connection failed: {str(e)}"}),
            500,
        )

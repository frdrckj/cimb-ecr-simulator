# CIMB ECR Simulator Web App (Fixed)

This is the updated CIMB ECR Simulator web application that follows the documentation for `CimbEcrSimulator.exe` and implements proper `ReqData` and `RspData` structures for communication with the CIMB APK on Verifone EDC through the ECR adaptor.

## Key Changes Made

### 1. Updated Backend Implementation
- **New file**: `src/routes/ecr_fixed.py` - Complete rewrite following the documentation
- **ReqData Structure**: Implemented proper fixed-length data structure as per documentation:
  - `chTransType` (1 byte) - Transaction type
  - `szAmount` (12 bytes) - Transaction amount 
  - `szInvNo` (6 bytes) - Invoice number
  - `szCardNo` (19 bytes) - Card number

- **RspData Structure**: Implemented comprehensive response parsing with all 25+ fields as per documentation:
  - Terminal ID, Merchant ID, Trace Number, Invoice Number
  - Entry Mode, Transaction Amounts, Card Details
  - Date/Time, Approval Code, Response Code
  - Reference Numbers, Installment Details, Point Rewards, etc.

### 2. Communication Protocol
- **Serial Communication**: Direct communication with ECR adaptor via serial port
- **Socket Communication**: Network communication with ECR adaptor via TCP/IP
- **Message Format**: Follows the exact byte-level protocol described in documentation
- **Error Handling**: Comprehensive error handling for communication failures

### 3. API Endpoints
- `POST /api/build_request` - Build request message in ReqData format
- `POST /api/process` - Process complete transaction (build request + send + parse response)
- `GET/POST /api/settings` - Manage ECR communication settings
- `GET /api/history` - Get transaction history
- `POST /api/test_connection` - Test connection to ECR adaptor

### 4. Frontend Updates
- Updated to use the new `/api/process` endpoint
- Maintains compatibility with existing UI
- Shows proper request/response data in ReqData/RspData format

## Installation and Setup

### Prerequisites
- Python 3.11+
- pip3

### Installation Steps

1. **Install Dependencies**
   ```bash
   pip3 install -r requirements.txt
   ```

2. **Run the Application**
   ```bash
   cd /path/to/cimb-ecr-simulator-fixed
   PYTHONPATH=/path/to/cimb-ecr-simulator-fixed python3 src/main.py
   ```

3. **Access the Web Interface**
   - Open browser to `http://localhost:5001`
   - Configure settings via the Settings button
   - Test transactions

## Configuration

### Serial Communication
- **Serial Port**: Select appropriate COM port (e.g., COM1, COM2, etc.)
- **Baud Rate**: 9600, 19200, 38400, 57600, or 115200
- **Data Bits**: 8 (default)
- **Stop Bits**: 1 or 2
- **Parity**: None, Even, or Odd

### Socket Communication
- **IP Address**: IP of the ECR adaptor (default: 127.0.0.1)
- **Port**: Port number (default: 9001)
- **SSL**: Enable/disable SSL encryption

## Usage

1. **Configure Connection**
   - Click "Settings" button
   - Choose communication type (Serial or Socket)
   - Configure connection parameters
   - Save settings

2. **Perform Transaction**
   - Select transaction type (SALE, VOID, REFUND, etc.)
   - Enter amount
   - Click "Send" to process transaction
   - View response in the Response area

3. **Monitor Results**
   - Check transaction history on the right panel
   - View detailed response data in JSON format
   - Monitor connection status

## Transaction Types Supported

- **SALE** (01) - Standard sale transaction
- **INSTALLMENT** (02) - Installment payment
- **VOID** (03) - Void previous transaction
- **REFUND** (04) - Refund transaction
- **QRIS MPM** (05) - QRIS Merchant Presented Mode
- **QRIS CPM** (0A) - QRIS Customer Presented Mode
- **QRIS NOTIFICATION** (06) - QRIS notification
- **QRIS REFUND** (07) - QRIS refund
- **POINT REWARD** (08) - Point reward transaction
- **TEST HOST** (09) - Test host connection
- **SETTLEMENT** (0B) - Settlement
- **REPRINT** (0C) - Reprint receipt
- **REPORT** (0D) - Generate report
- **LOGON** (0E) - Logon to system

## Technical Details

### Message Structure
The application now follows the exact `ReqData` and `RspData` structures as documented in `CimbEcrSimulator.exe`:

**Request Message (ReqData)**:
```
Offset | Size | Field        | Description
-------|------|--------------|------------------
0      | 1    | chTransType  | Transaction type
1      | 12   | szAmount     | Amount (padded)
13     | 6    | szInvNo      | Invoice number
19     | 19   | szCardNo     | Card number
```

**Response Message (RspData)**:
Contains 25+ fields including transaction details, card information, approval codes, and additional data as per the documentation.

### Communication Flow
1. **Build Request**: Create ReqData structure with transaction details
2. **Send Request**: Transmit via serial port or socket connection
3. **Receive Response**: Get response from ECR adaptor
4. **Parse Response**: Extract RspData structure from response bytes
5. **Display Results**: Show parsed data in JSON format

## Troubleshooting

### Common Issues

1. **"No serial port specified in settings"**
   - Configure serial port in Settings
   - Ensure correct COM port is selected

2. **"Serial communication error"**
   - Check serial port availability
   - Verify baud rate and other serial parameters
   - Ensure ECR adaptor is connected

3. **"Socket communication error"**
   - Verify IP address and port
   - Check network connectivity
   - Ensure ECR adaptor is listening on specified port

4. **"Error parsing response"**
   - Check ECR adaptor response format
   - Verify communication protocol compatibility

### Logging
- Application logs are written to `ecr_simulator.log`
- Check logs for detailed error information
- Log level can be adjusted in the code

## Compatibility

This implementation is designed to be compatible with:
- **CIMB ECR Adaptor** on Verifone EDC devices
- **CimbEcrSimulator.exe** protocol and data structures
- **Serial and Socket communication** methods
- **Windows and Linux** environments (with appropriate native libraries)

## Files Structure

```
cimb-ecr-simulator-fixed/
├── src/
│   ├── main.py                 # Flask application entry point
│   ├── routes/
│   │   ├── ecr_fixed.py       # Updated ECR implementation
│   │   └── ecr.py             # Original implementation (kept for reference)
│   └── static/
│       ├── index.html         # Web interface
│       ├── script.js          # Frontend JavaScript
│       └── style.css          # Styling
├── requirements.txt           # Python dependencies
└── README.md                 # This file
```

## Support

For issues or questions regarding this implementation, please refer to:
- The original `DocumentationforCimbEcrSimulator.md`
- Application logs in `ecr_simulator.log`
- Source code comments in `src/routes/ecr_fixed.py`

# cimb-ecr-simulator

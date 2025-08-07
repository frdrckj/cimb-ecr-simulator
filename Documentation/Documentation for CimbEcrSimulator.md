# Documentation for CimbEcrSimulator.exe

## 1. Introduction

This document provides a technical analysis of the `CimbEcrSimulator.exe` application, focusing on its internal workings, communication protocols, and integration with the CIMB application via an ECR (Electronic Cash Register) adaptor. The insights gathered from this analysis are intended to assist in the development of web applications that need to interface with similar ECR systems.

## 2. Overview of CimbEcrSimulator.exe

The `CimbEcrSimulator.exe` is a Windows executable that appears to be a Java application bundled with a native launcher (likely using Launch4j, as indicated by the extracted strings). Its primary purpose is to simulate interactions with an ECR system, specifically for CIMB and BRI (Bank Rakyat Indonesia) related transactions. The application utilizes the Java Native Access (JNA) library to communicate with underlying native libraries (DLLs on Windows, SO files on Linux) that handle the actual ECR communication.

## 3. Application Structure and Key Components

The decompilation process revealed several key Java classes that form the core of the simulator's functionality:

*   **`Main.java`**: This is the central entry point of the application. It initializes the `EcrLibrary` and sets up the main application frame. It also manages instances of `Communication`, `Serial`, and `SocketComm` classes, suggesting support for various communication methods.

*   **`CimbMain.java`**: This class specifically initializes the `Main` application with a `CimbEcrLibrary` instance and creates a `CimbMainFrame`. This indicates that the simulator can operate in a CIMB-specific mode.

*   **`BriMain.java`**: Similar to `CimbMain`, this class initializes the `Main` application with a `BriEcrLibrary` instance and creates a `BriMainFrame`, suggesting support for BRI-specific ECR interactions.

*   **`EcrLibrary.java`**: This is an abstract class that defines the common interface for ECR communication. It declares abstract methods for opening/closing sockets and serial ports, sending/receiving data, and packing/unpacking request/response messages. This abstraction allows for different ECR implementations (e.g., CIMB, BRI) to adhere to a common communication standard.

*   **`CimbEcrLibrary.java`**: This concrete implementation of `EcrLibrary` handles the CIMB-specific ECR communication. It uses JNA to load a native library (e.g., `CimbEcrLibrary.dll` on Windows or `libCimbEcrLibrary.so` on Linux) and provides methods to interact with it. This class is crucial for understanding how the simulator interfaces with the actual ECR adaptor.

## 4. Communication Protocols and ECR Adaptor Integration

The `CimbEcrLibrary` class is the bridge between the Java application and the native ECR adaptor. It leverages the Java Native Access (JNA) library to call functions within a native shared library (DLL/SO). The communication primarily occurs through two channels: **sockets** and **serial ports**.

### 4.1. Native Library Interaction (JNA)

The `CimbEcrLibrary` class dynamically loads a native library named `CimbEcrLibrary` (or `libCimbEcrLibrary.so` on Linux). This native library is expected to expose functions for ECR communication. The `ecrLibrary` interface within `CimbEcrLibrary.java` defines the native functions that are called:

*   `ecrGetVersion(byte[] var1)`: Retrieves the version of the native ECR library.
*   `ecrOpenSocket(byte[] var1, int var2, int var3)`: Opens a socket connection to the ECR adaptor. Parameters likely include IP address, port, and an SSL flag.
*   `ecrSendSocket(byte[] var1, int var2)`: Sends data over the open socket. Parameters include the data to send and its length.
*   `ecrRecvSocket(byte[] var1, int var2)`: Receives data from the socket. Parameters include a buffer to store received data and the maximum length to receive.
*   `ecrCloseSocket()`: Closes the socket connection.
*   `ecrOpenSerialPort(SerialData.ByReference var1)`: Opens a serial port connection. It takes a `SerialData` structure as input, which contains port details (e.g., COM port, baud rate, data bits, stop bits, parity).
*   `ecrSendSerialPort(byte[] var1, int var2)`: Sends data over the serial port.
*   `ecrRecvSerialPort(byte[] var1, int var2)`: Receives data from the serial port.
*   `ecrCloseSerialPort()`: Closes the serial port connection.
*   `ecrPackRequest(byte[] var1, ReqData.ByReference var2)`: Packs a request message into a byte array. It takes a `ReqData` structure containing transaction details.
*   `ecrParseResponse(byte[] var1, RspData.ByReference var2)`: Parses a response message from a byte array into an `RspData` structure.

### 4.2. Data Formats (`ReqData` and `RspData`)

The communication with the ECR adaptor involves structured data, defined by `ReqData` (Request Data) and `RspData` (Response Data) classes, which extend JNA's `Structure` class. These structures define the layout of the data exchanged with the native library.

#### 4.2.1. `ReqData` Structure

This structure is used to package transaction requests sent to the ECR adaptor. It contains the following fields:

| Field Name     | Type     | Size (Bytes) | Description                                    |
| :------------- | :------- | :----------- | :--------------------------------------------- |
| `chTransType`  | `byte`   | 1            | Transaction type (e.g., sale, void)            |
| `szAmount`     | `byte[]` | 12           | Transaction amount (e.g., "000000010000")      |
| `szInvNo`      | `byte[]` | 6            | Invoice number                                 |
| `szCardNo`     | `byte[]` | 19           | Card number                                    |

Example of `ReqData` packing (from `CimbEcrLibrary.java`):

```java
public byte[] packRequestMsg(String transType, long amount, long invoiceNo, String cardNo) {
    byte[] reqMsg = new byte[]{};
    if (ecrLib != null) {
        byte[] data = new byte[1024];
        ecrLibrary.ReqData.ByReference reqData = new ecrLibrary.ReqData.ByReference();
        reqData.chTransType = Utils.hexToByte(transType);
        reqData.szAmount = String.format("%010d00", amount).getBytes();
        reqData.szInvNo = String.format("%06d", invoiceNo).getBytes();
        reqData.szCardNo = Arrays.copyOf(Native.toByteArray(cardNo), reqData.szCardNo.length);
        int reqLen = ecrLib.ecrPackRequest(data, reqData);
        reqMsg = Arrays.copyOfRange(data, 0, reqLen);
    }
    return reqMsg;
}
```

#### 4.2.2. `RspData` Structure

This structure is used to parse transaction responses received from the ECR adaptor. It contains a more extensive set of fields:

| Field Name         | Type     | Size (Bytes) | Description                                  |
| :----------------- | :------- | :----------- | :------------------------------------------- |
| `chTransType`      | `byte`   | 1            | Transaction type                             |
| `szTID`            | `byte[]` | 8            | Terminal ID                                  |
| `szMID`            | `byte[]` | 15           | Merchant ID                                  |
| `szTraceNo`        | `byte[]` | 6            | Trace number                                 |
| `szInvoiceNo`      | `byte[]` | 6            | Invoice number                               |
| `chEntryMode`      | `byte`   | 1            | Entry mode (e.g., swipe, chip)               |
| `szTransAmount`    | `byte[]` | 12           | Transaction amount                           |
| `szTransAddAmount` | `byte[]` | 12           | Additional transaction amount                |
| `szTotalAmount`    | `byte[]` | 12           | Total amount                                 |
| `szCardNo`         | `byte[]` | 19           | Card number                                  |
| `szCardholderName` | `byte[]` | 26           | Cardholder name                              |
| `szDate`           | `byte[]` | 8            | Transaction date (YYYYMMDD)                  |
| `szTime`           | `byte[]` | 6            | Transaction time (HHMMSS)                    |
| `szApprovalCode`   | `byte[]` | 6            | Approval code                                |
| `szResponseCode`   | `byte[]` | 2            | Response code (e.g., "00" for approved)      |
| `szRefNumber`      | `byte[]` | 12           | Reference number                             |
| `szReferenceId`    | `byte[]` | 6            | Reference ID                                 |
| `szTerm`           | `byte[]` | 2            | Term (for installment plans)                 |
| `szMonthlyAmount`  | `byte[]` | 12           | Monthly installment amount                   |
| `szPointReward`    | `byte[]` | 9            | Point reward                                 |
| `szRedemptionAmount`| `byte[]` | 11           | Redemption amount                            |
| `szPointBalance`   | `byte[]` | 9            | Point balance                                |
| `szFiller`         | `byte[]` | 99           | Filler bytes                                 |

Example of `RspData` parsing (from `CimbEcrLibrary.java`):

```java
public static int parseResponseMsg(byte[] rspMsg) {
    int retVal = -99;
    if (ecrLib != null) {
        rspData = new ecrLibrary.RspData.ByReference();
        retVal = ecrLib.ecrParseResponse(rspMsg, rspData);
    }
    return retVal;
}
```

### 4.3. Communication Flow

The general communication flow between the simulator and the ECR adaptor (via the native library) would be:

1.  **Initialization**: The `CimbEcrLibrary` loads the native `CimbEcrLibrary.dll` (or `.so`).
2.  **Connection**: Depending on the configuration, the application calls `ecrOpenSocket` (for network communication) or `ecrOpenSerialPort` (for direct serial communication) to establish a connection with the ECR adaptor.
3.  **Request Preparation**: The application constructs a request by populating a `ReqData` structure with transaction details. This structure is then passed to `ecrPackRequest` to convert it into a byte array suitable for transmission.
4.  **Sending Request**: The packed request message (byte array) is sent to the ECR adaptor using `ecrSendSocket` or `ecrSendSerialPort`.
5.  **Receiving Response**: The application waits for a response from the ECR adaptor using `ecrRecvSocket` or `ecrRecvSerialPort`. The received data is a byte array.
6.  **Response Parsing**: The received byte array is then passed to `ecrParseResponse`, which populates an `RspData` structure with the parsed response details.
7.  **Processing Response**: The application processes the fields within the `RspData` structure to determine the transaction outcome (e.g., `szResponseCode`, `szApprovalCode`).
8.  **Disconnection**: After the transaction, the connection is closed using `ecrCloseSocket` or `ecrCloseSerialPort`.

## 5. Implications for Web Application Development

Developing a web application that communicates with the CIMB ECR adaptor based on this analysis presents several considerations:

*   **Backend Requirement**: Direct communication with native libraries (DLLs/SOs) from a web browser is not feasible due to security restrictions. Therefore, a backend service will be required to act as an intermediary between the web frontend and the ECR adaptor.

*   **Backend Technology**: The original simulator is written in Java. A Java-based backend (e.g., Spring Boot, Quarkus) would be a natural fit, allowing direct reuse or adaptation of the `CimbEcrLibrary` logic. Alternatively, other backend technologies (e.g., Node.js, Python, .NET) could be used, but they would need to implement their own JNA-like bindings to the native `CimbEcrLibrary.dll` or replicate its functionality.

*   **Communication with Backend**: The web frontend would communicate with this backend service using standard web protocols like HTTP/HTTPS (RESTful APIs, WebSockets). The backend service would then handle the low-level communication with the ECR adaptor.

*   **Data Serialization**: The `ReqData` and `RspData` structures define the data contracts. The web application's frontend and backend would need to serialize and deserialize data according to these formats. For example, JSON could be used for communication between the frontend and backend, and the backend would convert this JSON into the byte array format required by the native ECR library.

*   **Error Handling**: Robust error handling is crucial. The `CimbEcrLibrary` includes basic `try-catch` blocks for communication errors. The web application should implement comprehensive error handling, including network issues, ECR adaptor errors, and data parsing failures.

*   **Security**: If the ECR communication involves sensitive data (e.g., card numbers), ensure that all communication channels (frontend to backend, backend to ECR adaptor) are secured using appropriate encryption (HTTPS, SSL/TLS).

*   **Cross-Platform Considerations**: The `CimbEcrLibrary` explicitly checks for Windows vs. non-Windows environments to load the correct native library (`.dll` vs. `.so`). If the web application backend is deployed on a Linux server, the `libCimbEcrLibrary.so` would be required.

## 6. Conclusion

The `CimbEcrSimulator.exe` provides a clear blueprint for interacting with the CIMB ECR adaptor. The core logic resides in the `CimbEcrLibrary` class, which uses JNA to interface with a native library. This native library handles the actual socket and serial communication, as well as the packing and parsing of structured request and response messages. For web application development, a backend service is essential to bridge the web frontend with the native ECR communication. The defined `ReqData` and `RspData` structures will be critical for designing the data exchange between the web application components and the ECR system.


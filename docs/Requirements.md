# Types of Requirements are
Requirements

│

├── Functional

└── Non-Functional

**Functional Requirements**

These answer:

What should the system do?

Examples:

Capture images from a camera.
Detect motion.
Detect people.
Recognize known faces.
Save security events.
Send Telegram alerts.
Search events by time.

These become features.

**Non-Functional Requirements**

These answer:

How should the system behave?

Examples:

Start automatically after reboot.
Use less than 1 GB RAM.
Continue working if Wi-Fi disconnects.
Store logs safely.
Respond to Telegram commands within 5 seconds.

Notice these aren't features—they describe quality.

**Functional Requirements (v1)**
| ID    | Requirement                            |
| ----- | -------------------------------------- |
| FR-01 | Capture video from a camera.           |
| FR-02 | Detect motion.                         |
| FR-03 | Capture a snapshot when motion occurs. |
| FR-04 | Store event information in a database. |
| FR-05 | Send a Telegram notification.          |
| FR-06 | Respond to `/status`.                  |
| FR-07 | Respond to `/today`.                   |
| FR-08 | Save application logs.                 |


**Non-Functional Requirements**
| ID     | Requirement                                                                                    |
| ------ | ---------------------------------------------------------------------------------------------- |
| NFR-01 | The system should restart automatically after a crash.                                         |
| NFR-02 | The database must not be corrupted after a power outage.                                       |
| NFR-03 | API tokens must never be stored in source code.                                                |
| NFR-04 | Logs should include timestamps.                                                                |
| NFR-05 | The system should continue running without internet access, except for Telegram notifications. |

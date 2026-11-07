import smtplib
import socket
import ssl

import requests

from src.errors import UserFacingError


def describe_error(error) -> str:
    """A short description that is safe to store and show.

    NEVER use str(error): the text of network errors contains the full URL,
    which holds the Telegram bot token, webhook secret path or camera password.
    """
    if isinstance(error, UserFacingError):
        return str(error)
    if isinstance(error, requests.exceptions.HTTPError):
        status = getattr(error.response, "status_code", None)
        return f"The server answered with an error (HTTP {status})." if status else "The server answered with an error."
    if isinstance(error, requests.exceptions.Timeout):
        return "Timed out waiting for a reply."
    if isinstance(error, requests.exceptions.ConnectionError):
        return "Could not connect. Check the address and your internet connection."
    if isinstance(error, requests.exceptions.RequestException):
        return "The request failed."
    if isinstance(error, smtplib.SMTPAuthenticationError):
        return "The mail server rejected the username or password."
    if isinstance(error, smtplib.SMTPRecipientsRefused):
        return "The mail server refused the recipient address."
    if isinstance(error, smtplib.SMTPException):
        return "The mail server reported an error."
    if isinstance(error, ssl.SSLError):
        return "The secure connection failed. Check the security setting (SSL/STARTTLS)."
    if isinstance(error, (socket.timeout, TimeoutError)):
        return "Timed out."
    if isinstance(error, OSError):
        return "Could not connect. Check the address and your internet connection."
    return f"Unexpected error ({type(error).__name__})."

from typing import Any

from flask import request
from flask_socketio import emit
from typing_extensions import TypedDict

from asynction.exceptions import ValidationException


def ping(message: Any) -> None:
    # Dummy handler
    pass


class PingAck(TypedDict):
    ack: bool


def ping_with_ack(message: Any) -> PingAck:
    return PingAck(ack=True)


def connect() -> None:
    # Dummy handler
    pass


def disconnect() -> None:
    # Dummy handler
    pass


def some_error() -> None:
    # Dummy handler
    pass


def echo(message: str) -> bool:
    emit("echo", message)
    return True


def echo_with_invalid_ack(message: str) -> int:
    emit("echo", message)
    return 23


def authenticated_connect() -> None:
    assert request.args.get("token")


def echo_failed_validation(e: Exception) -> None:
    if isinstance(e, ValidationException):
        emit("echo errors", "Incoming message failed validation")

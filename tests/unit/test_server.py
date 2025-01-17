from typing import Optional
from unittest import mock

import pytest
from faker import Faker
from flask import Flask

from asynction.exceptions import MessageAckValidationException
from asynction.exceptions import PayloadValidationException
from asynction.exceptions import ValidationException
from asynction.server import AsynctionSocketIO
from asynction.server import SocketIO
from asynction.server import load_handler
from asynction.server import load_spec
from asynction.server import resolve_references
from asynction.types import GLOBAL_NAMESPACE
from asynction.types import AsyncApiSpec
from asynction.types import Channel
from asynction.types import ChannelBindings
from asynction.types import ChannelHandlers
from asynction.types import ErrorHandler
from asynction.types import Message
from asynction.types import MessageAck
from asynction.types import OneOfMessages
from asynction.types import Operation
from asynction.types import WebSocketsChannelBindings
from tests.fixtures import FixturePaths
from tests.fixtures.handlers import connect
from tests.fixtures.handlers import disconnect
from tests.fixtures.handlers import ping
from tests.fixtures.handlers import some_error
from tests.utils import deep_unwrap


def test_load_spec_instantiates_async_api_spec_object(fixture_paths: FixturePaths):
    spec = load_spec(fixture_paths.simple)
    assert isinstance(spec, AsyncApiSpec)


def test_asynction_socketio_from_spec(fixture_paths: FixturePaths):
    asio = AsynctionSocketIO.from_spec(spec_path=fixture_paths.simple)
    assert isinstance(asio, AsynctionSocketIO)


def test_asynction_socketio_from_spec_uses_spec_server_path_as_socketio_path(
    fixture_paths: FixturePaths,
):
    asio = AsynctionSocketIO.from_spec(
        spec_path=fixture_paths.simple_with_servers, server_name="production"
    )
    assert asio.server_options["path"] == "/api/socket.io"


def test_asynction_socketio_from_spec_path_kwarg_takes_precedence_over_server_name(
    fixture_paths: FixturePaths,
):
    p = "/async/socket.io"
    asio = AsynctionSocketIO.from_spec(
        spec_path=fixture_paths.simple_with_servers, path=p, server_name="production"
    )
    assert asio.server_options["path"] == p


def test_asynction_socketio_from_spec_resource_kwarg_takes_precedence_over_server_name(
    fixture_paths: FixturePaths,
):
    p = "/async/socket.io"
    asio = AsynctionSocketIO.from_spec(
        spec_path=fixture_paths.simple_with_servers,
        resource=p,
        server_name="production",
    )
    assert "path" not in asio.server_options
    assert asio.server_options["resource"] == p


def test_asynction_socketio_from_spec_empty_server_path_is_ignored(
    fixture_paths: FixturePaths,
):
    asio = AsynctionSocketIO.from_spec(
        spec_path=fixture_paths.simple_with_servers, server_name="development"
    )
    assert "path" not in asio.server_options


def test_asynction_socketio_from_spec_raises_value_error_for_non_existent_server_name(
    fixture_paths: FixturePaths,
):
    with pytest.raises(ValueError):
        AsynctionSocketIO.from_spec(
            spec_path=fixture_paths.simple_with_servers, server_name="not-production"
        )


def test_asynction_socketio_from_spec_registers_default_error_handler(
    fixture_paths: FixturePaths,
):
    def my_default_error_handler(_):
        # dummy handler
        pass

    asio = AsynctionSocketIO.from_spec(
        spec_path=fixture_paths.simple,
        default_error_handler=my_default_error_handler,
    )

    assert asio.default_exception_handler == my_default_error_handler


def test_resolve_references_resolves_successfully():
    raw_spec = {
        "channels": {
            "/chat": {
                "publish": {"message": {"$ref": "#/components/messages/UserMessage"}},
                "subscribe": {
                    "message": {
                        "oneOf": [
                            {"$ref": "#/components/messages/UserResponse"},
                            {"payload": {"type": "null"}},
                        ]
                    }
                },
                "bindings": {
                    "$ref": "#/components/channelBindings/AuthenticatedWsBindings"
                },
            }
        },
        "components": {
            "messages": {
                "UserMessage": {
                    "payload": {"type": "string"},
                    "x-handler": "my_func",
                    "x-ack": {"$ref": "#/components/x-messageAcks/UserMessageAck"},
                },
                "UserResponse": {"payload": {"type": "object"}},
            },
            "channelBindings": {
                "AuthenticatedWsBindings": {
                    "ws": {
                        "query": {
                            "type": "object",
                            "properties": {
                                "token": {"type": "string"},
                            },
                            "required": ["token"],
                        }
                    }
                }
            },
            "x-messageAcks": {"UserMessageAck": {"args": {"type": "object"}}},
        },
    }

    resolved = {
        "channels": {
            "/chat": {
                "publish": {
                    "message": {
                        "payload": {"type": "string"},
                        "x-ack": {"args": {"type": "object"}},
                        "x-handler": "my_func",
                    }
                },
                "subscribe": {
                    "message": {
                        "oneOf": [
                            {"payload": {"type": "object"}},
                            {"payload": {"type": "null"}},
                        ]
                    }
                },
                "bindings": {
                    "ws": {
                        "query": {
                            "type": "object",
                            "properties": {
                                "token": {"type": "string"},
                            },
                            "required": ["token"],
                        }
                    }
                },
            }
        },
        "components": {
            "messages": {
                "UserMessage": {
                    "payload": {"type": "string"},
                    "x-ack": {"args": {"type": "object"}},
                    "x-handler": "my_func",
                },
                "UserResponse": {"payload": {"type": "object"}},
            },
            "channelBindings": {
                "AuthenticatedWsBindings": {
                    "ws": {
                        "query": {
                            "type": "object",
                            "properties": {
                                "token": {"type": "string"},
                            },
                            "required": ["token"],
                        }
                    }
                }
            },
            "x-messageAcks": {"UserMessageAck": {"args": {"type": "object"}}},
        },
    }

    assert resolve_references(raw_spec) == resolved


def test_load_handler():
    handler_id = "tests.fixtures.handlers.ping"
    assert load_handler(handler_id) == ping


def test_register_handlers_registers_callables_with_correct_event_name_and_namespace(
    faker: Faker,
):
    namespace = f"/{faker.pystr()}"
    event_name = faker.word()
    spec = AsyncApiSpec(
        channels={
            namespace: Channel(
                publish=Operation(
                    message=OneOfMessages(
                        oneOf=[
                            Message(
                                name=event_name,
                                payload={"type": "object"},
                                x_handler="tests.fixtures.handlers.ping",
                            )
                        ]
                    ),
                )
            )
        }
    )
    server = AsynctionSocketIO(spec)

    server._register_handlers()
    assert len(server.handlers) == 1
    registered_event, registered_handler, registered_namespace = server.handlers[0]
    assert registered_event == event_name
    assert deep_unwrap(registered_handler) == ping
    assert registered_namespace == namespace


def test_register_handlers_registers_channel_handlers(
    faker: Faker,
):
    namespace = f"/{faker.pystr()}"
    spec = AsyncApiSpec(
        channels={
            namespace: Channel(
                x_handlers=ChannelHandlers(
                    connect="tests.fixtures.handlers.connect",
                    disconnect="tests.fixtures.handlers.disconnect",
                    error="tests.fixtures.handlers.some_error",
                )
            )
        }
    )
    server = AsynctionSocketIO(spec)

    server._register_handlers()

    assert server.exception_handlers[namespace] == some_error
    for event_name, handler, handler_namespace in server.handlers:
        assert handler_namespace == namespace
        unwrapped = deep_unwrap(handler)
        if event_name == "connect":
            assert unwrapped == connect
        else:
            assert unwrapped == disconnect


def test_register_handlers_adds_payload_validator_if_validation_is_enabled(
    faker: Faker,
):
    namespace = f"/{faker.pystr()}"
    event_name = faker.word()
    spec = AsyncApiSpec(
        channels={
            namespace: Channel(
                publish=Operation(
                    message=OneOfMessages(
                        oneOf=[
                            Message(
                                name=event_name,
                                payload={"type": "string"},
                                x_handler="tests.fixtures.handlers.ping",
                            )
                        ]
                    ),
                )
            )
        }
    )
    server = AsynctionSocketIO(spec, True)

    server._register_handlers()
    _, registered_handler, _ = server.handlers[0]
    handler_with_validation = deep_unwrap(registered_handler, depth=1)
    actual_handler = deep_unwrap(handler_with_validation)
    args = (faker.pyint(),)

    actual_handler(*args)  # actual handler does not raise validation errors
    with pytest.raises(PayloadValidationException):
        handler_with_validation(*args)


def test_register_handlers_adds_ack_validator_if_validation_is_enabled(faker: Faker):
    namespace = f"/{faker.pystr()}"
    event_name = faker.word()
    spec = AsyncApiSpec(
        channels={
            namespace: Channel(
                publish=Operation(
                    message=OneOfMessages(
                        oneOf=[
                            Message(
                                name=event_name,
                                payload={"type": "string"},
                                x_handler="tests.fixtures.handlers.ping_with_ack",
                                x_ack=MessageAck(
                                    args={
                                        "type": "object",
                                        "properties": {"ack": {"type": "number"}},
                                        "required": ["ack"],
                                    }
                                ),
                            )
                        ]
                    ),
                )
            )
        }
    )
    server = AsynctionSocketIO(spec, True)

    server._register_handlers()
    _, registered_handler, _ = server.handlers[0]
    handler_with_validation = deep_unwrap(registered_handler, depth=1)
    actual_handler = deep_unwrap(handler_with_validation)
    args = (faker.pystr(),)  # valid handler args

    # actual handler does not raise validation errors, although it returns invalid data
    actual_handler(*args)

    with pytest.raises(MessageAckValidationException):
        handler_with_validation(*args)


def test_register_handlers_omits_payload_validator_if_validation_is_disabled(
    faker: Faker,
):
    namespace = f"/{faker.pystr()}"
    event_name = faker.word()
    spec = AsyncApiSpec(
        channels={
            namespace: Channel(
                publish=Operation(
                    message=OneOfMessages(
                        oneOf=[
                            Message(
                                name=event_name,
                                payload={"type": "string"},
                                x_handler="tests.fixtures.handlers.ping",
                            )
                        ]
                    ),
                )
            )
        }
    )
    server = AsynctionSocketIO(spec, False)

    server._register_handlers()
    _, registered_handler, _ = server.handlers[0]
    handler_with_validation = deep_unwrap(registered_handler, depth=1)
    actual_handler = deep_unwrap(handler_with_validation)

    assert handler_with_validation == actual_handler
    args = (faker.pyint(),)
    handler_with_validation(*args)  # handler does not raise validation errors
    assert True


@pytest.mark.parametrize(
    argnames=["optional_error_handler"],
    argvalues=[[lambda _: None], [None]],
    ids=["with_default_error_handler", "without_default_error_handler"],
)
def test_register_handlers_registers_default_error_handler(
    optional_error_handler: Optional[ErrorHandler],
):
    server = AsynctionSocketIO(spec=AsyncApiSpec(channels={}))

    server._register_handlers(optional_error_handler)
    assert server.default_exception_handler == optional_error_handler


def test_register_namespace_handlers_wraps_bindings_validator_if_validation_enabled():
    channel_handlers = ChannelHandlers(connect="tests.fixtures.handlers.connect")
    channel_bindings = ChannelBindings(
        ws=WebSocketsChannelBindings(
            method="GET",
        )
    )
    server = AsynctionSocketIO(mock.Mock())

    server._register_namespace_handlers(
        GLOBAL_NAMESPACE, channel_handlers, channel_bindings
    )
    event_name, registered_handler, _ = server.handlers[0]
    assert event_name == "connect"
    handler_with_validation = deep_unwrap(registered_handler, depth=1)
    actual_handler = deep_unwrap(handler_with_validation)

    with Flask(__name__).test_client() as c:
        c.post()  # Inject invalid POST request
        actual_handler()  # actual handler does not raise validation errors
        with pytest.raises(ValidationException):
            handler_with_validation()


def test_register_namespace_handlers_omits_bindings_validator_if_validation_disabled():
    channel_handlers = ChannelHandlers(connect="tests.fixtures.handlers.connect")
    channel_bindings = ChannelBindings(
        ws=WebSocketsChannelBindings(
            method="GET",
        )
    )
    server = AsynctionSocketIO(mock.Mock(), False)

    server._register_namespace_handlers(
        GLOBAL_NAMESPACE, channel_handlers, channel_bindings
    )
    event_name, registered_handler, _ = server.handlers[0]
    assert event_name == "connect"
    handler_with_validation = deep_unwrap(registered_handler, depth=1)
    actual_handler = deep_unwrap(handler_with_validation)

    with Flask(__name__).test_client() as c:
        c.post()  # Inject invalid POST request
        assert handler_with_validation == actual_handler
        handler_with_validation()  # handler does not raise validation errors
        assert True


def test_emit_event_with_non_existent_namespace_raises_validation_exc(faker: Faker):
    namespace = f"/{faker.pystr()}"
    event_name = faker.pystr()
    spec = AsyncApiSpec(
        channels={
            namespace: Channel(
                subscribe=Operation(
                    message=OneOfMessages(
                        oneOf=[
                            Message(
                                name=event_name,
                                payload={"type": "object"},
                            )
                        ]
                    ),
                )
            )
        },
    )
    server = AsynctionSocketIO(spec)

    with pytest.raises(ValidationException):
        # Correct event name but no namespace:
        server.emit(event_name, faker.pydict(value_types=[str, int]))


def test_emit_event_that_has_no_subscribe_operation_raises_validation_exc(faker: Faker):
    namespace = f"/{faker.pystr()}"
    event_name = faker.pystr()
    spec = AsyncApiSpec(
        channels={
            namespace: Channel(
                publish=Operation(
                    message=OneOfMessages(
                        oneOf=[
                            Message(
                                name=event_name,
                                payload={"type": "object"},
                                x_handler="tests.fixtures.handlers.ping",
                            )
                        ]
                    ),
                )
            )
        },
    )
    server = AsynctionSocketIO(spec)

    with pytest.raises(ValidationException):
        server.emit(
            event_name, faker.pydict(value_types=[str, int]), namespace=namespace
        )


def test_emit_event_not_defined_under_given_valid_namespace_raises_validation_exc(
    faker: Faker,
):
    namespace = f"/{faker.pystr()}"
    spec = AsyncApiSpec(
        channels={
            namespace: Channel(
                subscribe=Operation(
                    message=OneOfMessages(
                        oneOf=[
                            Message(
                                name=faker.pystr(),
                                payload={"type": "object"},
                            )
                        ]
                    ),
                )
            )
        },
    )
    server = AsynctionSocketIO(spec)

    with pytest.raises(ValidationException):
        # Correct namespace but undefined event:
        server.emit(
            faker.pystr(), faker.pydict(value_types=[str, int]), namespace=namespace
        )


def test_emit_event_with_invalid_args_fails_validation(faker: Faker):
    namespace = f"/{faker.pystr()}"
    event_name = faker.pystr()
    spec = AsyncApiSpec(
        channels={
            namespace: Channel(
                subscribe=Operation(
                    message=OneOfMessages(
                        oneOf=[
                            Message(
                                name=event_name,
                                payload={"type": "number"},
                            )
                        ]
                    ),
                )
            )
        },
    )
    server = AsynctionSocketIO(spec)

    with pytest.raises(PayloadValidationException):
        # Event args do not adhere to the schema
        server.emit(event_name, faker.pystr(), namespace=namespace)


@mock.patch.object(SocketIO, "emit")
def test_emit_valid_event_invokes_super_method(
    super_method_mock: mock.Mock, faker: Faker
):
    namespace = f"/{faker.pystr()}"
    event_name = faker.pystr()
    spec = AsyncApiSpec(
        channels={
            namespace: Channel(
                subscribe=Operation(
                    message=OneOfMessages(
                        oneOf=[
                            Message(
                                name=event_name,
                                payload={"type": "string"},
                            )
                        ]
                    ),
                )
            )
        },
    )
    server = AsynctionSocketIO(spec)

    event_args = [faker.pystr()]
    server.emit(event_name, *event_args, namespace=namespace)
    super_method_mock.assert_called_once_with(
        event_name, *event_args, namespace=namespace
    )


@mock.patch.object(SocketIO, "emit")
def test_emit_validiation_is_ignored_if_validation_flag_is_false(
    super_method_mock: mock.Mock, faker: Faker
):
    namespace = f"/{faker.pystr()}"
    event_name = faker.pystr()
    spec = AsyncApiSpec(
        channels={
            namespace: Channel(
                subscribe=Operation(
                    message=OneOfMessages(
                        oneOf=[
                            Message(
                                name=event_name,
                                payload={"type": "number"},
                            )
                        ]
                    ),
                )
            )
        },
    )
    server = AsynctionSocketIO(spec, validation=False)

    event_args = [faker.pystr()]  # invalid args
    server.emit(event_name, *event_args, namespace=namespace)

    # super method called because validation was skipped
    super_method_mock.assert_called_once_with(
        event_name, *event_args, namespace=namespace
    )


@mock.patch.object(SocketIO, "emit")
def test_emit_event_wraps_callback_with_validator(
    super_method_mock: mock.Mock, faker: Faker
):
    namespace = f"/{faker.pystr()}"
    event_name = faker.pystr()
    spec = AsyncApiSpec(
        channels={
            namespace: Channel(
                subscribe=Operation(
                    message=OneOfMessages(
                        oneOf=[
                            Message(
                                name=event_name,
                                payload={"type": "number"},
                                x_ack=MessageAck(args={"type": "boolean"}),
                            )
                        ]
                    ),
                )
            )
        },
    )
    server = AsynctionSocketIO(spec)

    def actual_callback(*args):
        # dummy callback

        pass

    server.emit(
        event_name, faker.pyint(), namespace=namespace, callback=actual_callback
    )
    super_method_mock.assert_called_once()
    *_, kwargs = super_method_mock.call_args
    callback_with_validation = kwargs["callback"]

    callback_args = [
        faker.pystr()
    ]  # invalid callback args (should have been a boolean)

    # actual callback has no validation -- hence it does not fail
    actual_callback(*callback_args)

    with pytest.raises(MessageAckValidationException):
        callback_with_validation(*callback_args)

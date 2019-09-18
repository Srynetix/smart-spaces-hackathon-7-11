import asyncio
import json
import logging
import re
from typing import Any, Optional

from flask import Flask, request
from flask_mqtt import Mqtt
import requests
import xows

from . import config
from .api import get_camera_snapshot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["MQTT_BROKER_URL"] = config.MQTT_BROKER_URL
app.config["MQTT_BROKER_PORT"] = config.MQTT_BROKER_PORT
mqtt = Mqtt(app)

loop = asyncio.get_event_loop()

MQTT_TOPIC_RGX = re.compile(r"/merakimv/(?P<serial>[0-9A-Z-]+)/raw_detections")
CAMERA_STATE = {}

###########
# Utilities

def get_camera_room(camera_serial: str) -> Optional[dict]:
    """Get room associated to camera.

    Args:
        camera_serial (str): Camera serial

    Returns:
        Optional[dict]: Room information
    """
    # TODO
    raise NotImplementedError()


def get_camera_network(camera_serial: str) -> str:
    """Get network associated to camera.

    Args:
        camera_serial (str): Camera serial

    Returns:
        str: Network ID
    """
    # TODO
    raise NotImplementedError()


def get_room_meeting(room_id: str) -> Optional[dict]:
    """Get meeting associated to room.

    Args:
        room_id (str): Room ID

    Returns:
        Optional[dict]: Meeting information
    """
    # TODO
    raise NotImplementedError()


def get_room_t10(room_id: str) -> Optional[dict]:
    """Get T10 associated to room.

    Args:
        room_id (str): Room ID

    Returns:
        Optional[dict]: T10 information
    """


def take_picture_from_camera(network_id: str, camera_serial: str) -> dict:
    """Take picture from camera.

    Args:
        network_id (str): Network ID
        camera_serial (str): Camera serial

    Returns:
        dict: Picture data
    """
    data = get_camera_snapshot(network_id, camera_serial)
    if data.status_code != 202:
        # Fake data
        return {
            "url": "https://spn4.meraki.com/stream/jpeg/snapshot/b2d123asdf423qd22d2",
            "expiry": "Access to the image will expire one day"
        }

    return data.content


def identify_user(picture: str) -> Optional[dict]:
    """Identify user using picture.

    Args:
        picture (str): Picture data

    Returns:
        Optional[dict]: User information
    """
    # TODO
    raise NotImplementedError()


async def async_send_raw_message_to_t10(ip: str, username: str, password: str, message: str) -> dict:
    """Send raw message to T10.

    Args:
        ip (str): Device IP
        username (str): Username
        password (str): Password
        message (str): Message

    Returns:
        dict: Response
    """
    async with xows.XoWSClient(ip, username, password) as client:
        logger.info(f"Sending message {message} to T10 {ip} ...")
        return await client.xCommand(['Message', 'Send'], Text=message)


def send_raw_message_to_t10(ip: str, username: str, password: str, message: str) -> dict:
    """Send raw message to T10.

    Args:
        ip (str): Device IP
        username (str): Username
        password (str): Password
        message (str): Message

    Returns:
        dict: Response
    """
    return loop.run_until_complete(async_send_raw_message_to_t10(ip, username, password, message))


def send_json_message_to_t10(ip: str, username: str, password: str, message: dict) -> dict:
    """Send message to T10.

    Args:
        message (dict): Message to send

    Returns:
        dict: Response
    """
    json_data = json.dumps(message)
    return loop.run_until_complete(async_send_raw_message_to_t10(ip, username, password, f"JSON:{json_data}"))


def handle_t10_message(message: dict):
    """Handle T10 message.

    Args:
        message (dict): Message
    """
    # TODO
    raise NotImplementedError()


def handle_meraki_data(camera_serial: str, camera_data: dict):
    """Handle Meraki MQTT data.

    Args:
        camera_serial (str): Camera serial
        camera_data (dict): Camera data
    """
    global CAMERA_STATE

    objects = camera_data["objects"]
    persons = [o for o in objects if o["type"] == "person"]
    current_persons_count = len(persons)
    previous_persons_count = CAMERA_STATE.get(camera_serial, 0)

    if current_persons_count != previous_persons_count:
        logger.debug(f"[DEBUG] There are now {current_persons_count} people on camera {camera_serial} (previously {previous_persons_count})")

    # Update people count
    CAMERA_STATE[camera_serial] = current_persons_count


#############
# MQTT routes

@mqtt.on_connect()
def handle_connect(client, userdata, flags, rc):
    """Handle MQTT connections.

    Args:
        client (Client): MQTT client
        userdata (Any): User data
        flags (Any): Flags
        rc (Any): RC
    """
    for serial in config.MERAKI_CAMERA_SERIALS:
        mqtt.subscribe(f'/merakimv/{serial}/raw_detections')

@mqtt.on_message()
def handle_message(client, userdata, message):
    """Handle a MQTT incoming message.

    Args:
        client (Client): MQTT client
        userdata (Any): User data
        message (Message): Message object
    """
    match = MQTT_TOPIC_RGX.search(message.topic)
    if match:
        handle_meraki_data(match.group("serial"), json.loads(message.payload.decode()))

#############
# HTTP routes

@app.route('/message', methods=["POST"])
def message():
    """Wait for T10 incoming message.

    Returns:
        str: Route output
    """
    handle_t10_message(request.get_json())
    return "ok"


@app.route('/t10-message', methods=["POST"])
def t10_message():
    send_json_message_to_t10("10.89.130.68", "cisco", "cisco", request.get_json())
    return "ok"

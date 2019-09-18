import asyncio
import json
import logging
import re
from typing import Any, Optional

from flask import Flask, request
from flask_mqtt import Mqtt
import requests
import xows

from . import api, config
from meraki_sdk.meraki_sdk_client import MerakiSdkClient

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["MQTT_BROKER_URL"] = config.MQTT_BROKER_URL
app.config["MQTT_BROKER_PORT"] = config.MQTT_BROKER_PORT
mqtt = Mqtt(app)

loop = asyncio.get_event_loop()

MQTT_RAW_DETECTIONS_RGX = re.compile(r"/merakimv/(?P<serial>[0-9A-Z-]+)/raw_detections")
MQTT_ZONE_RGX = re.compile(r"/merakimv/(?P<serial>[0-9A-Z-]+)/(?P<zone_id>[0-9A-Z]+)")
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


def get_camera_network(camera_serial: str) -> dict:
    """Get network associated to camera.

    Args:
        camera_serial (str): Camera serial

    Returns:
        str: Network informations
    """
    client = MerakiSdkClient(config.MERAKI_AUTH_TOKEN)
    orgs = client.organizations.get_organizations()

    all_organizations = {}

    for org in orgs:
        all_organizations['organization_id'] = org['id']

    if all_organizations:  # make sure it's not an empty collection
        networks = client.networks.get_organization_networks(all_organizations)
        if networks:
            for network in networks:
                devices = client.devices.get_network_devices(network['id'])
                for device in devices:
                    if device['serial'] == camera_serial:
                        return network

    return {}


def get_room_meeting(room_id: str) -> Optional[dict]:
    """Get meeting associated to room.

    Args:
        room_id (str): Room ID

    Returns:
        Optional[dict]: Meeting information
    """
    return api.get_current_meeting_api(room_id)


def get_available_room(meeting_length: int) -> Optional[dict]:
    """Get meeting associated to room.

    Args:
        room_id (str): Room ID

    Returns:
        Optional[dict]: Meeting information
    """
    try:
        return api.get_available_room_api(meeting_length)
    except Exception as err:
        logger.log(str(err))

    raise NotImplementedError()


def get_room_t10(room_id: str) -> Optional[dict]:
    """Get T10 associated to room.

    Args:
        room_id (str): Room ID

    Returns:
        Optional[dict]: T10 information
    """
    return api.get_room_device_info_api(room_id)


def take_picture_from_camera(network_id: str, camera_serial: str) -> dict:
    """Take picture from camera.

    Args:
        network_id (str): Network ID
        camera_serial (str): Camera serial

    Returns:
        dict: Picture data
    """
    data = api.get_camera_snapshot(network_id, camera_serial)
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
    return api.identify_person_api(picture)


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
        encoded_message = f"711:{message}"
        logger.info(f"Sending message {encoded_message} to T10 {ip} ...")
        return await client.xCommand(['Message', 'Send'], Text=encoded_message)


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
    return loop.run_until_complete(async_send_raw_message_to_t10(ip, username, password, json_data))

def schedule_o365_meeting(meeting_information: dict):
    """Schedule O365 MEETING

    Args:
        message (dict): meeting_information
    """
    raise NotImplementedError()

def handle_t10_message(message: dict):
    """Handle T10 message.

    Args:
        message (dict): Message
    """
    # TODO
    print(message)

    try:
        if message["choice"] == "yes":
            send_json_message_to_t10("10.89.130.68", "cisco", "cisco", {
                "messageId": 2
            })

    except Exception as err:
        logger.debug(str(err))


def get_zone_name(camera_serial: str, zone_id: str) -> str:
    """Get zone name.

    Args:
        camera_serial (str): Camera serial
        zone_id (str): Zone ID

    Returns:
        str: Zone name
    """
    camera = next(x for x in config.MERAKI_CAMERAS if x["serial"] == camera_serial)
    zone = next(x for x in camera.get("zones", []) if x["id"] == zone_id)
    return zone["name"]

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


def handle_meraki_zone(camera_serial: str, zone_id: str, camera_data: dict):
    """Handle Meraki MQTT data.

    Args:
        camera_serial (str): Camera serial
        zone_id (str): Zone ID
        camera_data (dict): Camera data
    """
    global CAMERA_STATE
    zone_name = get_zone_name(camera_serial, zone_id)

    state_key = f"{camera_serial}-{zone_id}"
    previous_persons_count = CAMERA_STATE.get(state_key, 0)
    current_persons_count = camera_data["counts"]["person"]

    if zone_name == "Start" and current_persons_count > previous_persons_count:
        logger.debug(f"[DEBUG] Someone entered the room (camera: {camera_serial})")
        start_entered_scenario(camera_serial)

    if zone_name == "Far" and current_persons_count > previous_persons_count:
        logger.debug(f"[DEBUG] Someone is too far in the room (camera: {camera_serial})")

    CAMERA_STATE[state_key] = current_persons_count


def start_entered_scenario(camera_serial: str):
    # Get the network
    network = get_camera_network(camera_serial)
    # Get the camera capture
    capture = take_picture_from_camera(network["id"], camera_serial)
    # Identify person
    person = identify_user(capture["url"])
    # Get the room ID associated to the camera
    room_id = get_camera_room(camera_serial)
    # Get the T10 device associated to the room
    t10_info = api.get_room_t10(room_id)
    # Get the associated meeting (TODO: No hardcode)
    meeting = {
        "start_time": "0",
        "attendees": ["a@local.test", "b@local.test"],
        "subject": "Hello"
    }

    if meeting:
        send_json_message_to_t10(
            t10_info["credentials"]["IP"],
            t10_info["credentials"]["username"],
            t10_info["credentials"]["password"],
            {
                "messageId": 1,
                "username": person["username"]
            }
        )


def handle_bot_message(message: dict):
    """Handle bot message.

    Args:
        message (dict): Message
    """
    pass


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
    for camera in config.MERAKI_CAMERAS:
        serial = camera["serial"]
        zones = camera.get("zones", [])
        for zone in zones:
            zone_id = zone["id"]
            mqtt.subscribe(f'/merakimv/{serial}/{zone_id}')

@mqtt.on_message()
def handle_message(client, userdata, message):
    """Handle a MQTT incoming message.

    Args:
        client (Client): MQTT client
        userdata (Any): User data
        message (Message): Message object
    """
    match = MQTT_RAW_DETECTIONS_RGX.search(message.topic)
    if match:
        handle_meraki_data(match.group("serial"), json.loads(message.payload.decode()))

    match = MQTT_ZONE_RGX.search(message.topic)
    if match:
        handle_meraki_zone(match.group("serial"), match.group("zone_id"), json.loads(message.payload.decode()))

#############
# HTTP routes

@app.route('/on-t10-message', methods=["POST"])
def on_t10_message():
    """Wait for T10 incoming message.

    Returns:
        str: Route output
    """
    handle_t10_message(request.get_json())
    return "ok"


@app.route('/send-t10-message', methods=["POST"])
def send_t10_message():
    send_json_message_to_t10("10.89.130.68", "cisco", "cisco", request.get_json())
    return "ok"


@app.route('/on-bot-message', methods=["POST"])
def on_bot_message():
    """Wait for bot incoming message.

    Returns:
        str: Route output
    """
    handle_bot_message(request.get_json())
    return "ok"

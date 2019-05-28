#!/usr/local/bin/python python3

# This is based on an example at https://github.com/anki/cozmo-python-sdk/blob/master/examples/apps/remote_control_cozmo.py
# This file allows the user to control Cozmo with a keyboard, and displays Cozmo's live image feed. 

import asyncio
import io
import json
import math
import sys

sys.path.append('lib/')
import flask_helpers
import cozmo


try:
    from flask import Flask, request
except ImportError:
    sys.exit("Cannot import from flask: Do `pip3 install --user flask` to install")

try:
    from PIL import Image, ImageDraw
except ImportError:
    sys.exit("Cannot import from PIL: Do `pip3 install --user Pillow` to install")

try:
    import requests
except ImportError:
    sys.exit("Cannot import from requests: Do `pip3 install --user requests` to install")


DEBUG_ANNOTATIONS_DISABLED = 0
DEBUG_ANNOTATIONS_ENABLED_VISION = 1
DEBUG_ANNOTATIONS_ENABLED_ALL = 2


# Annotator for displaying RobotState (position, etc.) on top of the camera feed
class RobotStateDisplay(cozmo.annotate.Annotator):
    def apply(self, image, scale):
        d = ImageDraw.Draw(image)
        bounds = [3, 0, image.width, image.height]


def create_default_image(image_width, image_height, do_gradient=False):
    '''Create a place-holder PIL image to use until we have a live feed from Cozmo'''
    image_bytes = bytearray([0x70, 0x70, 0x70]) * image_width * image_height

    if do_gradient:
        i = 0
        for y in range(image_height):
            for x in range(image_width):
                image_bytes[i] = int(255.0 * (x / image_width))   # R
                image_bytes[i+1] = int(255.0 * (y / image_height))  # G
                image_bytes[i+2] = 0                                # B
                i += 3

    image = Image.frombytes('RGB', (image_width, image_height), bytes(image_bytes))
    return image


flask_app = Flask(__name__)
remote_control_cozmo = None
_default_camera_image = create_default_image(320, 240)
_is_mouse_look_enabled_by_default = False
_is_device_gyro_mode_enabled_by_default = False
_gyro_driving_deadzone_ratio = 0.025

_display_debug_annotations = DEBUG_ANNOTATIONS_ENABLED_ALL


def remap_to_range(x, x_min, x_max, out_min, out_max):
    '''convert x (in x_min..x_max range) to out_min..out_max range'''
    if x < x_min:
        return out_min
    elif x > x_max:
        return out_max
    else:
        ratio = (x - x_min) / (x_max - x_min)
        return out_min + ratio * (out_max - out_min)


class RemoteControlCozmo:

    def __init__(self, coz):
        self.cozmo = coz

        self.drive_forwards = 0
        self.drive_back = 0
        self.turn_left = 0
        self.turn_right = 0

        self.go_fast = 0
        self.go_slow = 0

        self.is_mouse_look_enabled = _is_mouse_look_enabled_by_default
        self.is_device_gyro_mode_enabled = _is_device_gyro_mode_enabled_by_default
        self.mouse_dir = 0

        self.action_queue = []


    def set_anim(self, key_index, anim_index):
        self.anim_index_for_key[key_index] = anim_index


    def handle_key(self, key_code, is_shift_down, is_ctrl_down, is_alt_down, is_key_down):
        print('In handle_key\n')
        print('Key code is: ', key_code, '\n')
        '''Called on any key press or release
           Holding a key down may result in repeated handle_key calls with is_key_down==True
        '''

        # Update desired speed / fidelity of actions based on shift/alt being held
        was_go_fast = self.go_fast
        was_go_slow = self.go_slow

        self.go_fast = is_shift_down
        self.go_slow = is_alt_down

        speed_changed = (was_go_fast != self.go_fast) or (was_go_slow != self.go_slow)

        # Update state of driving intent from keyboard, and if anything changed then call update_driving
        update_driving = True
        if key_code == 'X':
            is_key_down = False
            self.drive_forwards = False
            self.drive_back = False
            self.turn_left = False
            self.turn_right = False
        elif key_code == 'W':
            self.drive_forwards = is_key_down
        elif key_code == 'S':
            self.drive_back = is_key_down
        elif key_code == 'A':
            self.turn_left = is_key_down
        elif key_code == 'D':
            self.turn_right = is_key_down            
        else:
            if not speed_changed:
                update_driving = False


        # Update driving, head and lift as appropriate
        if update_driving:
            self.update_mouse_driving()
            
    def queue_action(self, new_action):
        if len(self.action_queue) > 10:
            self.action_queue.pop(0)
        self.action_queue.append(new_action)

    def update(self):
        '''Try and execute the next queued action'''
        if len(self.action_queue) > 0:
            queued_action, action_args = self.action_queue[0]
            if queued_action(action_args):
                self.action_queue.pop(0)


    def pick_speed(self, fast_speed, mid_speed, slow_speed):
        if self.go_fast:
            if not self.go_slow:
                return fast_speed
        elif self.go_slow:
            return slow_speed
        return mid_speed


    def scale_deadzone(self, value, deadzone, maximum):
        if math.fabs(value) > deadzone:
            adjustment = math.copysign(deadzone, value)
            scaleFactor = maximum / (maximum - deadzone)
            return (value - adjustment) * scaleFactor
        else:
            return 0

    
    def update_mouse_driving(self):
        print('in update_mouse_driving\n')
        drive_dir = (self.drive_forwards - self.drive_back)

        if (drive_dir > 0.1) and self.cozmo.is_on_charger:
            # cozmo is stuck on the charger, and user is trying to drive off - issue an explicit drive off action
            try:
                # don't wait for action to complete - we don't want to block the other updates (camera etc.)
                self.cozmo.drive_off_charger_contacts()
            except cozmo.exceptions.RobotBusy:
                # Robot is busy doing another action - try again next time we get a drive impulse
                pass

        turn_dir = (self.turn_right - self.turn_left) + self.mouse_dir
        if drive_dir < 0:
            # It feels more natural to turn the opposite way when reversing
            turn_dir = -turn_dir

        forward_speed = self.pick_speed(150, 75, 50)
        turn_speed = self.pick_speed(100, 50, 30)

        l_wheel_speed = (drive_dir * forward_speed) + (turn_speed * turn_dir)
        r_wheel_speed = (drive_dir * forward_speed) - (turn_speed * turn_dir)

        self.cozmo.drive_wheels(l_wheel_speed, r_wheel_speed, l_wheel_speed*4, r_wheel_speed*4 )

@flask_app.route("/", methods = ['GET', 'POST'])
def handle_index_page():
    print('in handle_index_page\n')
    # while True: 
    printing = 'Waiting\n'
    if request.method == 'POST':
        print('FOUND A POST\n')
        handle_key_event(request, True)
        printing = 'Received\n'
    return printing
    

def get_annotated_image():
    image = remote_control_cozmo.cozmo.world.latest_image
    if _display_debug_annotations != DEBUG_ANNOTATIONS_DISABLED:
        image = image.annotate_image(scale=2)
    else:
        image = image.raw_image
    return image

def serve_single_image():
    if remote_control_cozmo:
        try:
            image = get_annotated_image()
            if image:
                return flask_helpers.serve_pil_image(image)
        except cozmo.exceptions.SDKShutdown:
            requests.post('shutdown')
    return flask_helpers.serve_pil_image(_default_camera_image)

def is_microsoft_browser(request):
    agent = request.user_agent.string
    return 'Edge/' in agent or 'MSIE ' in agent or 'Trident/' in agent

@flask_app.route("/cozmoImage")
def handle_cozmoImage():
    if is_microsoft_browser(request):
        return serve_single_image()
    return flask_helpers.stream_video(streaming_video, request.url_root)

def handle_key_event(key_request, is_key_down):
    # TO DO: what is the form/data going to be when it comes in from Unity??
    # Should it be one request at a time or a set of x number of key strokes? 
    # How can we make it continuous?? 
    print('In handle_key_event\n')
    message = key_request.form['message']
    if remote_control_cozmo:
        remote_control_cozmo.handle_key(key_code=message, is_shift_down=False,
                                        is_ctrl_down=False, is_alt_down=False,
                                        is_key_down=is_key_down)
    return ""

@flask_app.route('/shutdown', methods=['POST'])
def shutdown():
    flask_helpers.shutdown_flask(request)
    return ""

@flask_app.route('/updateCozmo', methods=['POST'])
def handle_updateCozmo():
    if remote_control_cozmo:
        remote_control_cozmo.update()
    return ""

def run(sdk_conn):
    print('in run\n')
    robot = sdk_conn.wait_for_robot()
    robot.world.image_annotator.add_annotator('robotState', RobotStateDisplay)
    robot.enable_device_imu(True, True, True)

    global remote_control_cozmo
    remote_control_cozmo = RemoteControlCozmo(robot)

    # Turn on image receiving by the camera
    robot.camera.image_stream_enabled = True
    robot.camera.color_image_enabled = True

    flask_helpers.run_flask(flask_app)

if __name__ == '__main__':
    cozmo.setup_basic_logging()
    cozmo.robot.Robot.drive_off_charger_on_connect = False  # RC can drive off charger if required
    try:
        print('In the try\n')
        cozmo.connect(run)
    except KeyboardInterrupt as e:
        pass
    except cozmo.ConnectionError as e:
        sys.exit("A connection error occurred: %s" % e)

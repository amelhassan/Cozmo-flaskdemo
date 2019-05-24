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
        if key_code == ord('W'):
            self.drive_forwards = is_key_down
        elif key_code == ord('S'):
            self.drive_back = is_key_down
        elif key_code == ord('A'):
            self.turn_left = is_key_down
        elif key_code == ord('D'):
            self.turn_right = is_key_down
        elif key_code == ord('X'):
        	is_key_down = False
        else:
            if not speed_changed:
                update_driving = False


        # Update driving, head and lift as appropriate
        if update_driving:
            self.update_mouse_driving()


        # Handle any keys being released (e.g. the end of a key-click)
        if not is_key_down:
            if (key_code >= ord('0')) and (key_code <= ord('9')):
                anim_name = self.key_code_to_anim_name(key_code)
                self.play_animation(anim_name)
            elif key_code == ord(' '):
                self.say_text(self.text_to_say)


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



def to_js_bool_string(bool_value):
    return "true" if bool_value else "false"


@flask_app.route("/", methods = ['POST'])
def handle_index_page():
    # if request.method == 'POST':
    # 	handle_key_event(request, True)
    return '''
    <html>
        <head>
            <title>remote_control_cozmo.py display</title>
        </head>
        <body>
            <h1>Remote Control Cozmo</h1>
            <table>
                    <td valign = top>
                        <div id="cozmoImageMicrosoftWarning" style="display: none;color: #ff9900; text-align: center;">Video feed performance is better in Chrome or Firefox due to mjpeg limitations in this browser</div>
                        <img src="cozmoImage" id="cozmoImageId" width=640 height=480>
                        <div id="DebugInfoId"></div>
                    </td>
                    <td width=30></td>
                    <td valign=top>
                        <h2>Controls:</h2>


                        <b>W A S D</b> : Drive Forwards / Left / Back / Right<br><br>

                        <div style="display: none;">
                        <b>Q</b> : Toggle Mouse Look: <button id="mouseLookId" onClick=onMouseLookButtonClicked(this) style="font-size: 14px">Default</button><br>
                        </div>

                        <b>Shift</b> : Hold to Move Faster <br>
                        <b>Alt</b> : Hold to Move Slower <br>
                        <div style="display: none;">
                        <b>L</b> : Toggle IR Headlight: <button id="headlightId" onClick=onHeadlightButtonClicked(this) style="font-size: 14px">Default</button><br>
                        <b>O</b> : Toggle Debug Annotations: <button id="debugAnnotationsId" onClick=onDebugAnnotationsButtonClicked(this) style="font-size: 14px">Default</button><br>
                        <b>P</b> : Toggle Free Play mode: <button id="freeplayId" onClick=onFreeplayButtonClicked(this) style="font-size: 14px">Default</button><br>
                        <b>Y</b> : Toggle Device Gyro mode: <button id="deviceGyroId" onClick=onDeviceGyroButtonClicked(this) style="font-size: 14px">Default</button><br>
                        </div>
                    </td>
            </table>

            <script type="text/javascript">
                var gLastClientX = -1
                var gLastClientY = -1
                var gIsMouseLookEnabled = '''+ to_js_bool_string(_is_mouse_look_enabled_by_default) + '''
                var gAreDebugAnnotationsEnabled = '''+ str(_display_debug_annotations) + '''
                var gIsHeadlightEnabled = false
                var gIsFreeplayEnabled = false
                var gIsDeviceGyroEnabled = false
                var gUserAgent = window.navigator.userAgent;
                var gIsMicrosoftBrowser = gUserAgent.indexOf('MSIE ') > 0 || gUserAgent.indexOf('Trident/') > 0 || gUserAgent.indexOf('Edge/') > 0;
                var gSkipFrame = false;

                if (gIsMicrosoftBrowser) {
                    document.getElementById("cozmoImageMicrosoftWarning").style.display = "block";
                }

                function postHttpRequest(url, dataSet)
                {
                    var xhr = new XMLHttpRequest();
                    xhr.open("POST", url, true);
                    xhr.send( JSON.stringify( dataSet ) );
                }

                function updateCozmo()
                {
                    if (gIsMicrosoftBrowser && !gSkipFrame) {
                        // IE doesn't support MJPEG, so we need to ping the server for more images.
                        // Though, if this happens too frequently, the controls will be unresponsive.
                        gSkipFrame = true;
                        document.getElementById("cozmoImageId").src="cozmoImage?" + (new Date()).getTime();
                    } else if (gSkipFrame) {
                        gSkipFrame = false;
                    }
                    var xhr = new XMLHttpRequest();
                    xhr.onreadystatechange = function() {
                        if (xhr.readyState == XMLHttpRequest.DONE) {
                            document.getElementById("DebugInfoId").innerHTML = xhr.responseText
                        }
                    }

                    xhr.open("POST", "updateCozmo", true);
                    xhr.send( null );
                    setTimeout(updateCozmo , 60);
                }
                setTimeout(updateCozmo , 60);

                function updateButtonEnabledText(button, isEnabled)
                {
                    button.firstChild.data = isEnabled ? "Enabled" : "Disabled";
                }

                function onMouseLookButtonClicked(button)
                {
                    gIsMouseLookEnabled = !gIsMouseLookEnabled;
                    updateButtonEnabledText(button, gIsMouseLookEnabled);
                    isMouseLookEnabled = gIsMouseLookEnabled
                    postHttpRequest("setMouseLookEnabled", {isMouseLookEnabled})
                }

                function updateDebugAnnotationButtonEnabledText(button, isEnabled)
                {
                    switch(gAreDebugAnnotationsEnabled)
                    {
                    case 0:
                        button.firstChild.data = "Disabled";
                        break;
                    case 1:
                        button.firstChild.data = "Enabled (vision)";
                        break;
                    case 2:
                        button.firstChild.data = "Enabled (all)";
                        break;
                    default:
                        button.firstChild.data = "ERROR";
                        break;
                    }
                }

                function onDebugAnnotationsButtonClicked(button)
                {
                    gAreDebugAnnotationsEnabled += 1;
                    if (gAreDebugAnnotationsEnabled > 2)
                    {
                        gAreDebugAnnotationsEnabled = 0
                    }

                    updateDebugAnnotationButtonEnabledText(button, gAreDebugAnnotationsEnabled)

                    areDebugAnnotationsEnabled = gAreDebugAnnotationsEnabled
                    postHttpRequest("setAreDebugAnnotationsEnabled", {areDebugAnnotationsEnabled})
                }

                function onHeadlightButtonClicked(button)
                {
                    gIsHeadlightEnabled = !gIsHeadlightEnabled;
                    updateButtonEnabledText(button, gIsHeadlightEnabled);
                    isHeadlightEnabled = gIsHeadlightEnabled
                    postHttpRequest("setHeadlightEnabled", {isHeadlightEnabled})
                }

                function onFreeplayButtonClicked(button)
                {
                    gIsFreeplayEnabled = !gIsFreeplayEnabled;
                    updateButtonEnabledText(button, gIsFreeplayEnabled);
                    isFreeplayEnabled = gIsFreeplayEnabled
                    postHttpRequest("setFreeplayEnabled", {isFreeplayEnabled})
                }

                function onDeviceGyroButtonClicked(button)
                {
                    gIsDeviceGyroEnabled = !gIsDeviceGyroEnabled;
                    updateButtonEnabledText(button, gIsDeviceGyroEnabled);
                    isDeviceGyroEnabled = gIsDeviceGyroEnabled
                    postHttpRequest("setDeviceGyroEnabled", {isDeviceGyroEnabled})
                }

                updateButtonEnabledText(document.getElementById("mouseLookId"), gIsMouseLookEnabled);
                updateButtonEnabledText(document.getElementById("headlightId"), gIsHeadlightEnabled);
                updateDebugAnnotationButtonEnabledText(document.getElementById("debugAnnotationsId"), gAreDebugAnnotationsEnabled);
                updateButtonEnabledText(document.getElementById("freeplayId"), gIsFreeplayEnabled);
                updateButtonEnabledText(document.getElementById("deviceGyroId"), gIsDeviceGyroEnabled);

                function handleDropDownSelect(selectObject)
                {
                    selectedIndex = selectObject.selectedIndex
                    itemName = selectObject.name
                    postHttpRequest("dropDownSelect", {selectedIndex, itemName});
                }

                function handleKeyActivity (e, actionType)
                {
                    var keyCode  = (e.keyCode ? e.keyCode : e.which);
                    var hasShift = (e.shiftKey ? 1 : 0)
                    var hasCtrl  = (e.ctrlKey  ? 1 : 0)
                    var hasAlt   = (e.altKey   ? 1 : 0)

                    if (actionType=="keyup")
                    {
                        if (keyCode == 76) // 'L'
                        {
                            // Simulate a click of the headlight button
                            onHeadlightButtonClicked(document.getElementById("headlightId"))
                        }
                        else if (keyCode == 79) // 'O'
                        {
                            // Simulate a click of the debug annotations button
                            onDebugAnnotationsButtonClicked(document.getElementById("debugAnnotationsId"))
                        }
                        else if (keyCode == 80) // 'P'
                        {
                            // Simulate a click of the debug annotations button
                            onFreeplayButtonClicked(document.getElementById("freeplayId"))
                        }
                        else if (keyCode == 81) // 'Q'
                        {
                            // Simulate a click of the mouse look button
                            onMouseLookButtonClicked(document.getElementById("mouseLookId"))
                        }
                        else if (keyCode == 89) // 'Y'
                        {
                            // Simulate a click of the device gyro button
                            onDeviceGyroButtonClicked(document.getElementById("deviceGyroId"))
                        }
                    }

                    postHttpRequest(actionType, {keyCode, hasShift, hasCtrl, hasAlt})
                }

                function handleMouseActivity (e, actionType)
                {
                    var clientX = e.clientX / document.body.clientWidth  // 0..1 (left..right)
                    var clientY = e.clientY / document.body.clientHeight // 0..1 (top..bottom)
                    var isButtonDown = e.which && (e.which != 0) ? 1 : 0
                    var deltaX = (gLastClientX >= 0) ? (clientX - gLastClientX) : 0.0
                    var deltaY = (gLastClientY >= 0) ? (clientY - gLastClientY) : 0.0
                    gLastClientX = clientX
                    gLastClientY = clientY

                    postHttpRequest(actionType, {clientX, clientY, isButtonDown, deltaX, deltaY})
                }

                function handleTextInput(textField)
                {
                    textEntered = textField.value
                    postHttpRequest("sayText", {textEntered})
                }

                document.addEventListener("keydown", function(e) { handleKeyActivity(e, "keydown") } );
                document.addEventListener("keyup",   function(e) { handleKeyActivity(e, "keyup") } );

                document.addEventListener("mousemove",   function(e) { handleMouseActivity(e, "mousemove") } );

                function stopEventPropagation(event)
                {
                    if (event.stopPropagation)
                    {
                        event.stopPropagation();
                    }
                    else
                    {
                        event.cancelBubble = true
                    }
                }

                document.getElementById("sayTextId").addEventListener("keydown", function(event) {
                    stopEventPropagation(event);
                } );
                document.getElementById("sayTextId").addEventListener("keyup", function(event) {
                    stopEventPropagation(event);
                } );
            </script>

        </body>
    </html>
    '''

def get_annotated_image():
    image = remote_control_cozmo.cozmo.world.latest_image
    if _display_debug_annotations != DEBUG_ANNOTATIONS_DISABLED:
        image = image.annotate_image(scale=2)
    else:
        image = image.raw_image
    return image

def streaming_video(url_root):
    '''Video streaming generator function'''
    try:
        while True:
            if remote_control_cozmo:
                image = get_annotated_image()
                # TODO: send to particle filter here

                img_io = io.BytesIO()
                image.save(img_io, 'PNG')
                img_io.seek(0)
                yield (b'--frame\r\n'
                    b'Content-Type: image/png\r\n\r\n' + img_io.getvalue() + b'\r\n')
            else:
                asyncio.sleep(.1)
    except cozmo.exceptions.SDKShutdown:
        # Tell the main flask thread to shutdown
        requests.post(url_root + 'shutdown')

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


@flask_app.route('/setAreDebugAnnotationsEnabled', methods=['POST'])
def handle_setAreDebugAnnotationsEnabled():
    '''Called from Javascript whenever debug-annotations mode is toggled'''
    message = json.loads(request.data.decode("utf-8"))
    global _display_debug_annotations
    _display_debug_annotations = message['areDebugAnnotationsEnabled']
    if remote_control_cozmo:
        if _display_debug_annotations == DEBUG_ANNOTATIONS_ENABLED_ALL:
            remote_control_cozmo.cozmo.world.image_annotator.enable_annotator('robotState')
        else:
            remote_control_cozmo.cozmo.world.image_annotator.disable_annotator('robotState')
    return ""


@flask_app.route('/keydown', methods=['POST'])
def handle_keydown():
    '''Called from Javascript whenever a key is down (note: can generate repeat calls if held down)'''
    return handle_key_event(request, is_key_down=True)


@flask_app.route('/keyup', methods=['POST'])
def handle_keyup():
    '''Called from Javascript whenever a key is released'''
    return handle_key_event(request, is_key_down=False)

@flask_app.route('/updateCozmo', methods=['POST'])
def handle_updateCozmo():
    if remote_control_cozmo:
        remote_control_cozmo.update()
    return ""

# def get_in_position(robot: cozmo.robot.Robot):
#     lift_action = robot.set_lift_height(1.0, in_parallel=True)
#     head_action = robot.set_head_angle(cozmo.robot.MIN_HEAD_ANGLE,
#                                        in_parallel=True)
#     lift_action.wait_for_completed()
#     head_action.wait_for_completed()

def run(sdk_conn):
    robot = sdk_conn.wait_for_robot()
    robot.world.image_annotator.add_annotator('robotState', RobotStateDisplay)
    robot.enable_device_imu(True, True, True)

    # get_in_position(robot)

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
        cozmo.connect(run)
    except KeyboardInterrupt as e:
        pass
    except cozmo.ConnectionError as e:
        sys.exit("A connection error occurred: %s" % e)

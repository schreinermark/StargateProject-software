import sys
import tty
import termios

class KeyboardManager:

    def __init__(self, stargate):

        self.stargate = stargate
        self.log = stargate.log
        self.cfg = stargate.cfg
        self.audio = stargate.audio
        self.addr_manager = stargate.addr_manager
        self.address_book = stargate.addr_manager.get_book()

        self.shift_pressed = False

        if sys.platform != "darwin":
            import keyboard # pylint: disable=import-outside-toplevel
            keyboard.on_press(self.handle_keyboard_keypress)
            keyboard.on_release_key("shift", self.handle_keyboard_release_shift)

        self.log.log("Listening for input from the DHD. You can abort with the '-' key.")

    @staticmethod
    def get_key_map():
      ## the dictionary containing the key to symbol-number relations.
        return {'8': 1, 'C': 2, 'V': 3, 'U': 4, 'a': 5, '3': 6, '5': 7, 'S': 8, 'b': 9, 'K': 10, 'X': 11, 'Z': 12,
                          'E': 14, 'P': 15, 'M': 16, 'D': 17, 'F': 18, '7': 19, 'c': 20, 'W': 21, '6': 22, 'G': 23, '4': 24,
                          'B': 25, 'H': 26, 'R': 27, 'L': 28, '2': 29, 'N': 30, 'Q': 31, '9': 32, 'J': 33, '0': 34, 'O': 35,
                          'T': 36, 'Y': 37, '1': 38, 'I': 39
                          }

    @staticmethod
    def get_abort_characters():
        # If these symbols are entered, the gate will shutdown
        return [ '-', '\x03' ]  # '\x03' == Ctrl-C

# ++++ START: STDIN keyboard handling (for Console/SSH) +++++++

    @staticmethod
    def wait_for_keypress_stdin():
        """
        This helper function blocks the thread, waiting for a single character+\n from STDIN
        :return: The pressed char is returned.
        """

        file_desc = sys.stdin.fileno()
        old_settings = termios.tcgetattr(file_desc)
        try:
            tty.setraw(sys.stdin.fileno())
            char = sys.stdin.read(1)
        finally:
            termios.tcsetattr(file_desc, termios.TCSADRAIN, old_settings)

        self.handle_keypress_char(char)

    def service_stdin(self):
        """
        This function takes the stargate as input and listens for user input (from the DHD or keyboard). The pressed key
        is converted to a stargate symbol number as seen in this document: https://www.rdanderson.com/stargate/glyphs/index.htm
        This function is run in parallel in its own thread.
        :return: Nothing is returned, but the stargate is manipulated.
        """

        self.log.log("Listening for input from the Dialer. You can abort with the '-' key.")
        while self.stargate.running: # Keep running and ask for user input
            char = self.wait_for_keypress_stdin() #Save the input key as a variable
            self.handle_keypress_char(char)

# ++++ END: STDIN keyboard handling +++++++

# ++++ START: raw keyboard handling (for DHD)+++++++

    def handle_keyboard_keypress(self, key):
        if key.name == 'shift':
            self.shift_pressed = True
        else:
            if self.shift_pressed:
                key.name = key.name.upper()

        self.handle_keypress_char(key.name)

    def handle_keyboard_release_shift(self, event): # pylint: disable=unused-argument
        self.shift_pressed = False

# ++++ END: raw keyboard handling (for DHD)+++++++

    def handle_keypress_char(self, char):
        # This function takes a character read in by either input method, looks
        #  up the associated symbol index (if valid), and queues the symbol
        #  to the outgoing_symbol_buffer

        ## Convert the key to the correct symbol_number. ##
        try:
            symbol_number = self.get_key_map()[char]  # convert key press to symbol_number
        except KeyError:  # if the pressed button is not a key in the self.key_symbol_map dictionary
            symbol_number = 'unknown'
            if char in self.get_abort_characters():
                symbol_number = 'abort'
            elif char == 'A':
                symbol_number = 'centre_button_outgoing'
                self.log.log(f'key: {char} -> symbol: {symbol_number} CENTER')
            else:
                self.log.log(f'key: {char} -> symbol: {symbol_number} SYMBOL')

        ## If the user inputs the - key to abort. Not possible from the DHD.
        if char in self.get_abort_characters():
            self.log.log("Abort Requested: Shutting down any active wormholes, stopping the gate.")
            self.stargate.wormhole_active = False # Shutdown any open wormholes (particularly if turned on via web interface)
            self.stargate.running = False  # Stop the stargate object from running.

        ## If the user hits the centre_button
        if char == 'A':
            self.queue_center_button()

        # If we are hitting symbols on the DHD.
        else:
            self.queue_symbol(symbol_number)

    # Move to Dialer
    def queue_symbol(self, symbol_number):
        self.audio.play_random_clip("DHD")
        if symbol_number != 'unknown' and symbol_number not in self.stargate.address_buffer_outgoing:
            # If we have not yet activated the centre_button
            if not (self.stargate.centre_button_outgoing or self.stargate.centre_button_incoming):
                self.stargate.dialer.hardware.set_symbol_on( symbol_number ) # Light this symbol on the DHD

                # Append the symbol to the outgoing address buffer
                self.stargate.address_buffer_outgoing.append(symbol_number)
                self.log.log(f'address_buffer_outgoing: {self.stargate.address_buffer_outgoing}') # Log the address_buffer

    # Move to Dialer
    def queue_center_button(self):
        self.audio.play_random_clip("DHD")
        # If we are dialing
        if len(self.stargate.address_buffer_outgoing) > 0 and not self.stargate.wormhole_active:
            self.stargate.centre_button_outgoing = True
            self.stargate.dialer.hardware.set_center_on() # Activate the centre_button_outgoing light
        # If an outgoing wormhole is established
        if self.stargate.wormhole_active == 'outgoing':
            # TODO: We shouldn't be doing subspace-y stuff in the keyboard manager
            if self.addr_manager.is_fan_made_stargate(self.stargate.address_buffer_outgoing) \
             and self.stargate.fan_gate_online_status: # If we are connected to a fan_gate
                self.stargate.subspace_client.send_to_remote_stargate(self.addr_manager.get_ip_from_stargate_address(self.stargate.address_buffer_outgoing), 'centre_button_incoming')
            if not self.stargate.black_hole: # If we did not dial the black hole.
                self.stargate.wormhole_active = False # cancel outgoing wormhole

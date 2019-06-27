class ActionResult:

    def __init__(self, success, exit_code, *, messages=None, announce_message=''):
        self.success = success
        self.exit_code = exit_code
        self.messages = messages if messages is not None else []
        self.announce_message = announce_message

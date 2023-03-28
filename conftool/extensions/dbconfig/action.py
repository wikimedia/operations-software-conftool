from pathlib import Path
from subprocess import PIPE, Popen, TimeoutExpired


PHASTE_EXECUTABLE = "/usr/local/bin/phaste"


class ActionResult:
    def __init__(self, success, exit_code, *, messages=None, announce_message=""):
        self.success = success
        self.exit_code = exit_code
        self.messages = messages if messages is not None else []
        self.announce_message = announce_message


def phaste(title, message):
    """Publish a message with a given title as a Phabricator paste and return its URL as string."""
    if not Path(PHASTE_EXECUTABLE).exists():
        return "Skipping phaste: {path} not found".format(path=PHASTE_EXECUTABLE)

    try:
        proc = Popen(
            [PHASTE_EXECUTABLE, "--title", title], stdin=PIPE, stdout=PIPE, universal_newlines=True
        )
        outs, errs = proc.communicate(input=message, timeout=5)
        proc.terminate()
    except TimeoutExpired:
        proc.kill()
        outs, errs = proc.communicate()
        if outs is None or not outs:
            outs = "Unable to send diff to phaste"

    return outs.strip()

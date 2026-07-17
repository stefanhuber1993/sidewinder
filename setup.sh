#!/bin/bash
set -e

# Installs the native hidapi library plus the Python deps.
# The hid Python package binds to hidapi, and hidapi is what talks to the OS HID
# stack: IOKit on macOS, hidraw on Linux, hid.dll on Windows.

install_hidapi() {
    if [ "$(uname -s)" = "Darwin" ]; then
        if ! brew list hidapi &>/dev/null; then
            echo "Installing hidapi via Homebrew..."
            brew install hidapi
        fi
        return
    fi

    # Linux: the package name differs per distro. Skip if it's already there.
    if ldconfig -p 2>/dev/null | grep -q libhidapi; then
        echo "hidapi already installed."
        return
    fi

    if command -v apt-get &>/dev/null; then
        echo "Installing hidapi via apt..."
        sudo apt-get install -y libhidapi-hidraw0
    elif command -v dnf &>/dev/null; then
        echo "Installing hidapi via dnf..."
        sudo dnf install -y hidapi
    elif command -v pacman &>/dev/null; then
        echo "Installing hidapi via pacman..."
        sudo pacman -S --needed --noconfirm hidapi
    else
        echo "No supported package manager found. Install hidapi yourself, then re-run."
        exit 1
    fi
}

install_hidapi

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

echo
echo "Done. Run: source venv/bin/activate"

if [ "$(uname -s)" != "Darwin" ]; then
    cat <<'EOF'

Linux note: /dev/hidraw* is root-only by default, so the joystick needs a udev
rule before it works without sudo:

  echo 'SUBSYSTEM=="hidraw", ATTRS{idVendor}=="045e", ATTRS{idProduct}=="001b", MODE="0666"' \
    | sudo tee /etc/udev/rules.d/99-sidewinder-ff2.rules
  sudo udevadm control --reload-rules && sudo udevadm trigger

Then unplug and replug the joystick.
EOF
fi

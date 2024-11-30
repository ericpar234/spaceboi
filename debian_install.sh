#!/bin/bash

DESKTOP_FILE="./spaceboi.desktop"
VENV_PATH="$(pwd)/venv"
INSTALL_PATH="$HOME/.local/share/applications"
ICON_FILE="./assets/spaceboi.png"


if [ ! -f "$DESKTOP_FILE" ]; then
    echo "Desktop file $DESKTOP_FILE not found."
    exit 1
fi

if [ ! -d "$VENV_PATH" ]; then
    echo "Virtual environment path $VENV_PATH not found."
    exit 1
fi
if [ ! -f "$ICON_FILE" ]; then
    echo "Icon file $ICON_FILE not found."
    exit 1
fi

echo "Copying files to $INSTALL_PATH"

cp "$DESKTOP_FILE" "$INSTALL_PATH/spaceboi.desktop"
cp "$ICON_FILE" "$INSTALL_PATH/spaceboi.png"

# Modify the desktop file to use the virtual environment
EXEC_LINE="Exec=bash -c 'source $VENV_PATH/bin/activate && python3 -m spaceboi --mode gui'"

# Ensure the Exec line is deleted
if grep -q "^Exec=" "$INSTALL_PATH/$DESKTOP_FILE"; then
    sed -i "/^Exec=/d" "$INSTALL_PATH/$DESKTOP_FILE"
fi

# Re-add the Exec line
echo "$EXEC_LINE" >> "$INSTALL_PATH/$DESKTOP_FILE"

ICON_LINE="Icon=$INSTALL_PATH/spaceboi.png"
# Use sed to replace the Icon line in the .desktop file
sed -i "s|^Icon=.*|$ICON_LINE|" "$INSTALL_PATH/$DESKTOP_FILE"

echo "Modified $INSTALL_PATH/$DESKTOP_FILE to use virtual environment at $VENV_PATH"

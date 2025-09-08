#!/bin/bash
echo "Building Apple Helper Tool..."
swiftc -o ResistineHelper main.swift CodesignCheck.swift

echo "Installing to system..."
sudo cp ResistineHelper /usr/local/bin/
sudo cp com.resistine.plist /Library/LaunchDaemons/
sudo launchctl bootstrap system /Library/LaunchDaemons/com.resistine.plist

echo "Helper tool installed and running!"
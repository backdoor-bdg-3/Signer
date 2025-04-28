#!/bin/bash

# Exit on error
set -e

echo "===== STARTING ZSIGN INSTALLATION ====="

echo "Installing dependencies..."
apt-get update
apt-get install -y git cmake clang libssl-dev openssl zlib1g-dev libzip-dev libminizip-dev

echo "Cloning zsign repository..."
# Clean up previous installation if exists
rm -rf /tmp/zsign
git clone https://github.com/zhlynn/zsign.git /tmp/zsign

echo "Building zsign..."
cd /tmp/zsign
g++ -c src/*.cpp src/common/*.cpp -I./src -I./src/common -I/usr/include/minizip
g++ -o zsign *.o -lcrypto -lz -lzip -lminizip

echo "Installing zsign..."
# Make sure /usr/local/bin exists
mkdir -p /usr/local/bin

# Copy zsign to /usr/local/bin and make it executable
cp zsign /usr/local/bin/
chmod +x /usr/local/bin/zsign

# Create a symlink in /usr/bin as well for extra assurance
if [ ! -f /usr/bin/zsign ]; then
    ln -sf /usr/local/bin/zsign /usr/bin/zsign
fi

# Verify installation
echo "Testing zsign installation..."
if [ -f /usr/local/bin/zsign ]; then
    echo "zsign binary exists at /usr/local/bin/zsign"
    ls -la /usr/local/bin/zsign
else
    echo "ERROR: zsign binary not found at /usr/local/bin/zsign"
    exit 1
fi

if [ -f /usr/bin/zsign ]; then
    echo "zsign symlink exists at /usr/bin/zsign"
    ls -la /usr/bin/zsign
fi

echo "Verifying zsign runs correctly..."
/usr/local/bin/zsign -v || {
    echo "ERROR: zsign command failed to run"
    exit 1
}

echo "Cleaning up..."
cd -
rm -rf /tmp/zsign

echo "Current PATH: $PATH"
echo "zsign has been successfully installed!"
echo "===== ZSIGN INSTALLATION COMPLETE ====="
#!/bin/bash

# Exit on error
set -e

echo "Installing dependencies..."
apt-get update
apt-get install -y git cmake clang libssl-dev openssl zlib1g-dev libzip-dev libminizip-dev

echo "Cloning zsign repository..."
git clone https://github.com/zhlynn/zsign.git /tmp/zsign

echo "Building zsign..."
cd /tmp/zsign
g++ -c src/*.cpp src/common/*.cpp -I./src -I./src/common -I/usr/include/minizip
g++ -o zsign *.o -lcrypto -lz -lzip -lminizip

echo "Installing zsign..."
cp zsign /usr/local/bin/

echo "Testing zsign installation..."
zsign -v

echo "Cleaning up..."
cd -
rm -rf /tmp/zsign

echo "zsign has been successfully installed!"
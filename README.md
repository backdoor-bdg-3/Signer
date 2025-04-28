# Backdoor Web Signer

A powerful web application for signing iOS apps with your own certificates and provisioning profiles.

## Features

- Sign iOS apps of any size (1MB to 10GB+)
- Fast and efficient signing process
- Secure file handling with immediate cleanup
- Beautiful dark-themed UI with LED effects
- Support for custom certificates and provisioning profiles
- Custom app icon replacement
- Bundle ID, name, and version customization
- OTA installation for direct device installation
- Advanced signing options with dylib injection and custom entitlements
- Entitlements extraction and selection from IPA and provisioning profile

## Requirements

- Python 3.9+
- Flask
- zsign (included)
- OpenSSL
- libzip

## Installation

1. Clone the repository:
   ```
   git clone https://github.com/backdoor-bdg-3/Signer.git
   cd Signer
   ```

2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

3. Install zsign and dependencies:
   ```
   chmod +x install_zsign.sh
   sudo ./install_zsign.sh
   ```

4. Run the application:
   ```
   python app.py
   ```

### Docker Installation

Alternatively, you can use Docker:

```
docker build -t backdoor-web-signer .
docker run -p 12000:12000 backdoor-web-signer
```

## Usage

1. Upload your IPA file, P12 certificate, and mobile provision profile
2. Enter your P12 certificate password
3. (Optional) Customize bundle ID, name, version, or app icon
4. Click "Sign App"
5. Install the signed app directly on your device or download the IPA file

### Advanced Usage

For more control over the signing process, use the Advanced Signing page:

- Custom entitlements with extraction and selection from IPA and provisioning profile
- Dylib injection
- Compression control
- Weak signature for older iOS versions
- Force signature option
- Verbose output

#### Entitlements Extraction

The advanced mode includes a powerful entitlements extraction feature:

1. Upload your IPA and provisioning profile
2. Click "Extract Entitlements" button
3. View and select entitlements from both the app and provisioning profile
4. Apply selected entitlements to your signing process

This feature helps you:
- Understand what entitlements are in your app and provisioning profile
- Identify mismatches between app entitlements and provisioning profile
- Customize entitlements for specific use cases
- Ensure all required entitlements are included in the signed app
- Remove unnecessary entitlements that might cause issues

The entitlements table shows:
- The entitlement key
- The entitlement value
- The source (IPA or Provisioning Profile)
- A checkbox to include/exclude each entitlement

## Deployment

The application includes a `render.yaml` file for easy deployment on Render.com:

```
render deploy
```

## Contact

- Discord: xbl_bdg
- Telegram: elchops

## License

This project is licensed under the MIT License - see the LICENSE file for details.
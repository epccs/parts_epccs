# Documentation of parts_epccs

## Project Overview

This repository is the JSON data for an Inventory Management System. The goal is to use the data in a live Inventree system which is designed for intuitive parts management and stock control.

## Container Instalation

This repository currently contains instructions for setting up the system containers.

[./BACKEND_SETUP_1.0.x.md](BACKEND_SETUP_1.0.x.md)

[./BACKEND_DEVSETUP_1.0.x.md](BACKEND_DEVSETUP_1.0.x.md)

## JSON data

JSON files are used to load the Inventory Management System after it is configured. Some are present but only a few at this stage.

[Parts_JSON.md](Parts_JSON.md)

## Setup GitHub CLI on the Linux backend

```bash
# Configure Git Identity
git config --global user.name "Your Name"
git config --global user.email "your.email@example.com"

# Install the necessary dependencies and the GPG key:
sudo apt update
sudo apt install -y curl gnupg
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo gpg --dearmor -o /usr/share/keyrings/githubcli-archive-keyring.gpg

# Add the GitHub CLI repository to your system's sources list:
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null

# Update packages and install the GitHub CLI:
sudo apt update
sudo apt install gh -y
gh --version

# Authenticate GitHub CLI (I used browser on remote)
gh auth login
```

```text
? Where do you use GitHub? GitHub.com
? What is your preferred protocol for Git operations on this host? HTTPS
? Authenticate Git with your GitHub credentials? Yes
? How would you like to authenticate GitHub CLI? Login with a web browser

! First copy your one-time code: ####-####
Press Enter to open https://github.com/login/device in your browser... gh auth login
Error: no DISPLAY environment variable specified
✓ Authentication complete.
- gh config set -h github.com git_protocol https
✓ Configured git protocol
✓ Logged in as your_gh_user
```

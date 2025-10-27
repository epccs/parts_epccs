# Documentation of Learning InvenTree

## Project Overview

This repository documents various aspects of Learning InvenTree an Inventory Management System. The goal is to be able to store Parts, BOM, and other aspects of the system as JSON files in this repository. Programs will also be generated to syncronize the Parts and BOM data in InvenTree with this repository.

## Container Instalation

InvenTree setup instructions.

[./BACKEND_SETUP_1.0.x.md](BACKEND_SETUP_1.0.x.md)

[./BACKEND_DEVSETUP_1.0.x.md](BACKEND_DEVSETUP_1.0.x.md)

## data

The data folder holds JSON files that mirror the Inventory Management System.

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
gh auth status
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

## Clone this repository

```bash
cd ~
mkdir -p ~/git
cd ~/git
git clone https://github.com/epccs/parts_epccs.git ~/git/parts_epccs
cd ~/git/parts_epccs
```

## Environment Variables

```bash
nano ~/.profile
```

The python scritps in the /api folder need some environment variables set. The token is set in InvenTree in the `Account Setting` >> `User Settings` then select `Access Tokens`. If the user has the proper permission they can generate Tokens (ask an AI how to set the correct permission.)

```text
# set Inventree environment
export INVENTREE_TOKEN='your-token'
export INVENTREE_URL='http://inventree.local/'
```

## Some help from AI

- [Grok share - Parts & Categories, Companies](https://grok.com/share/c2hhcmQtMw%3D%3D_98fc7a9b-0c39-4cc2-9fa6-67a040b6f3b3)
- [Grok share - Resolve git merge conflict](https://grok.com/share/c2hhcmQtMw%3D%3D_3f2fb7da-5d90-45d7-b483-9f28a2f9108e)

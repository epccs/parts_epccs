# Docker on Linux

Some things that I needed to know to use Docker on Linux

## Create the docker group (if it doesn't exist)

I find that running "docker container ls" without sudo results in a "permission denied" error.

The Docker daemon runs as the root user and communicates through a Unix socket located at /var/run/docker.sock. By default, this socket is owned by the root user, limiting access to the root user or members of the docker group.

look for and if needed create the docker group (if it doesn't exist):

```bash
cat /etc/group | grep "docker" 
sudo groupadd docker
# log out for change to take effect
```

For security you will not want to add the group, just keep using sudo.

## Install Docker on Ubuntu

The package list for Docker on Ubuntu is: docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

```bash
# Update the apt package index to use the official Docker repository (in ca-certificates) 
# to allow apt to use a repository over HTTPS
sudo apt-get update
sudo apt install ca-certificates curl apt-transport-https software-properties-common lsb-release
# Add Docker's GPG key:
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
# Now, add the Docker repository to your apt sources
printf "deb [arch=%s signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu %s stable\n" "$(dpkg --print-architecture)" "$(. /etc/os-release && echo "$VERSION_CODENAME")" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
# update the apt package index again
sudo apt-get update
# check the version
apt show docker-ce -a
# now we are cooking, just need to install the official Docker packages
sudo apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
# Verify Docker Installation
sudo docker run hello-world
```

if somthing is wrong this is how to nuke docker

```bash
apt list --installed docker-ce docker-ce-cli containerd.io
docker version
# the latest atm is 28.3.2
docker container ls
# That should tell you what is going to stop, and this will stop the current Docker.
service docker.socket stop
service docker stop
sudo apt-get purge docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo rm -rf /var/lib/docker
sudo rm -rf /var/lib/containerd
```

I think apt (Ubuntu) will automaticly update these packages but that will be a lessen for another day.

## Install Inventree's Docker packages

Inventree wants to use port 80 so I need to remove Apache which I was looking at for some reason.

```bash
sudo systemctl stop apache2
sudo apt-get purge apache2 apache2-utils apache2-bin apache2-data
sudo apt-get autoremove
```

These notes are for my setup, for your own it is better to use the ones Inventree provides.

<https://docs.inventree.org/en/stable/start/docker/>

remove previous setup then get the latest: "docker-compose.yml", ".env", and  "Caddyfile". My working folder is ~/InvenTree_prod.

```bash
cd ~/InvenTree_prod
docker volume rm -f inventree-production_inventree_data
curl -o ~/InvenTree_prod/docker-compose.yml https://raw.githubusercontent.com/inventree/inventree/bca375dae5ac1d49bb5388393360c461639dbbb8/contrib/container/docker-compose.yml
curl -o ~/InvenTree_prod/.env https://raw.githubusercontent.com/inventree/inventree/bca375dae5ac1d49bb5388393360c461639dbbb8/contrib/container/.env
curl -o ~/InvenTree_prod/Caddyfile https://raw.githubusercontent.com/inventree/inventree/bca375dae5ac1d49bb5388393360c461639dbbb8/contrib/container/Caddyfile
```

Change the .env file to match the setup. I need to name the host as inventree next time, but for now it will stay what it is. The host is setup with with an HD (/dev/sdaX) and an NVM (/dev/nvme0n1pX). I have maped 100Gb (/dev/sda1) to /home/inventree/database, but next time I will map it to /home/inventree/inventree-data.

Now run "docker compose" which will take some time.

```bash
cd ~/InvenTree_prod
docker compose run --rm inventree-server invoke update
# bring up the containers
docker compose up -d
# and to stop it 
docker compose down
```

# Docker on Linux

Docker has been the recomended way to Install Inventree. These are some things that I needed to know to use Docker on Linux.

## Add Docker group to admin account

When using Docker, you typically don't create a dedicated system user for InvenTree itself. Instead, InvenTree runs inside its Docker containers, and the containers operate with their own internal user (often a non-root user for security).

Running "docker container ls" without sudo results in a "permission denied" error.

The Docker daemon runs as the root user and communicates through a Unix socket located at /var/run/docker.sock. By default, this socket is owned by the root user, limiting access to the root user or members of the docker group.

```bash
# if the group exist it will be reported
sudo groupadd docker
sudo usermod -aG docker $USER
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
# the latest atm is 28.3.3
docker container ls
# That should tell you what is going to stop, and this will stop the current Docker.
service docker.socket stop
service docker stop
sudo apt-get purge docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo rm -rf /var/lib/docker
sudo rm -rf /var/lib/containerd
```

I think apt (Ubuntu) will automaticly update these packages but that will be a lessen for another day.

## Database Storage and Backup

The host I have to run this on has an NVM which has two mounts one for the root and the other for Linux EFI images. It also has a slow HDD. I was thinking of puting the PostgreSQL storage on the HDD but that will make Inventree slow, it would be better to use the HDD for backups, and just operate out of the NVM/SSD.

```bash
# place working database on fast NVM/SSD e.g., in the .env file set INVENTREE_EXT_VOLUME=/homer/sutherland/inventree-data
rsutherland@inventree2:~$ mkdir -p ~/inventree-data/{data,media,static,backup}
# To do a backup run (schedule it with cron). Restore with "invoke restore". ### this is for later not now ###
docker compose exec inventree-server invoke backup
# use samba to make the backup visable, so make a mount ponit for the HDD (dev/sda on my setup).
rsutherland@inventree2:~$ mkdir -p ~/samba
# instructions for seting up the partition are not provided here
rsutherland@beryllium:~$ cat /etc/fstab
# /etc/fstab: static file system information.
#
# Use 'blkid' to print the universally unique identifier for a
# device; this may be used with UUID= as a more robust way to name devices
# that works even if disks are added and removed. See fstab(5).
#
# <file system> <mount point>   <type>  <options>       <dump>  <pass>
# / was on /dev/sdb2 during curtin installation
/dev/disk/by-uuid/abd83287-89b8-4edc-9baa-6a14f1f3d5cf / ext4 defaults 0 1
# /boot/efi was on /dev/sdb1 during curtin installation
/dev/disk/by-uuid/F9ED-2F9C /boot/efi vfat defaults 0 1
/swap.img       none    swap    sw      0       0
# end of fstab

# use an editor to add the mount to to the end of fstab
rsutherland@beryllium:~$ sudo nano /etc/fstab
# e.g., 
/dev/sda1 /home/rsutherland/samba auto defaults,auto_da_alloc 0 0
# next mount it. Old comand was: sudo mount -a
rsutherland@beryllium:~$ systemctl daemon-reload
# rsync ~/inventree-data/backup to your Samba mount periodically (e.g., via a cron job). This avoids runtime issues.
```

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
cd ~
mkdir inventree-docker
docker volume rm -f inventree-production_inventree_data
curl -o ~/inventree-docker/docker-compose.yml https://raw.githubusercontent.com/inventree/inventree/stable/contrib/container/docker-compose.yml
curl -o ~/inventree-docker/.env https://raw.githubusercontent.com/inventree/inventree/stable/contrib/container/.env
curl -o ~/inventree-docker/Caddyfile https://raw.githubusercontent.com/inventree/inventree/stable/contrib/container/Caddyfile
```

Change the .env file to match the setup. I need to name the host as inventree next time, but for now it will stay what it is. I have maped 100Gb (/dev/sda1) to /home/inventree/inventree-database-backup. The live database will run on the NVM at /home/inventree/inventree-docker/inventree-data.

Now run "docker compose" which will take some time.

```bash
cd ~
mkdir inventree-docker
cd ~/inventree-docker
# 4. Pull Latest Docker Images
docker compose pull
# Start the InvenTree stack in detached mode:
docker compose up -d
# Ensure required Python packages are installed.
# Create a new (empty) database.
# Perform necessary schema updates to create database tables.
# Update translation and static files.
docker compose run --rm inventree-server invoke update
# If superuser (admin) account is not set up in .env
docker compose run inventree-server invoke superuser
# bring up the containers (-d is detached mode)
docker compose up -d
# and to stop it. The -v flag removes associated volumes, including PostgreSQL data, to ensure clean start
docker compose down -v
# Clear the persistent database data to avoid conflicts:
sudo rm -rf ~/inventree-docker/inventree-data
```

This goes in stages, so when I need to fix some things.

```bash
cd ~/InvenTree_prod
docker compose down --volumes --rmi all --remove-orphans
docker system prune
```

## To Do List

Notes to remind me what I am working on

- host name inventree.local has issue of locking up at somewhat random times, seems to be temperature dependent, it is runing Windows with some stress test to see if problem duplicats.

- host name inventree2.local is an older machine but shoudl allow progress until the issue with the other is sorted. 
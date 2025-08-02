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
# set permissions for inventree docker container’s internal user (UID/GID 1000)
rsutherland@inventree2:~$ sudo chown -R 1000:1000 ~/inventree_data
# To do a backup run (schedule it with cron). Restore with "invoke restore". ### this is for later not now ###
rsutherland@inventree2:~$ docker compose exec inventree-server invoke backup
# make a mount ponit for the HDD (dev/sda on my setup)
rsutherland@inventree2:~$ sudo mkdir /srv/samba-share

# instructions for seting up the partition are not provided here
rsutherland@inventree2:~$ cat /etc/fstab
```

```conf
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
```

Use an editor to add the mount to to the end of fstab

```bash
rsutherland@inventree2:~$ sudo nano /etc/fstab
```

```
/dev/sda1 /srv/samba-share auto defaults,nofail 0 0
```

```bash
# next mount it and set premission.
rsutherland@inventree2:~$ systemctl daemon-reload
# next use samba to make the backup visabl and mounted to this location
rsutherland@inventree2:~$ mkdir -p ~/samba
```

Note that samba is serving the HDD mount, and it is not clear if that will be problems.

```conf
# add this to the very end of the /etc/samba/smb.conf file
[Samba-Inventree]
comment = Inventree Data Share
path = /srv/samba-share
browsable = yes
read only = no
guest ok = no
create mask = 0775
directory mask = 0775
valid users = rsutherland
```

The Samba share at ~/samba needs to be setup with uid=1000,gid=1000,forceuid,forcegid to avoid permission issues with Inventree. Example /etc/fstab entry:

```bash
# use an editor to add the mount to to the end of fstab
rsutherland@inventree2:~$ sudo nano /etc/fstab
```

```conf
//inventree2/Samba-Inventree /home/rsutherland/samba cifs credentials=/etc/samba/samba_credentials.conf,uid=1000,gid=1000,forceuid,forcegid 0 0
```

Create a file to store your credentials. A good location is in a secure system location. E.g., /etc/samba/samba_credentials.conf for a system-wide mount.

```bash
# use an editor to add the mount to to the end of fstab
rsutherland@inventree2:~$ sudo nano /etc/samba/samba_credentials.conf
```

```conf
username=your_samba_user
password=your_password
```

```bash
# save and exit then secure so only the root user look at it
sudo chmod 600 /etc/samba/samba_credentials.conf
sudo smbpasswd -a your_samba_user
sudo systemctl restart smbd nmbd
# with the HDD mounted create the backup volume
rsutherland@inventree2:~$ mkdir -p ~/samba/inventree-backup
# the samba mount will force the uid and gid to be what the container is happy with
```

## Install Inventree's Docker packages

These notes are for my setup, for your own it is better to use the ones Inventree provides.

<https://docs.inventree.org/en/stable/start/docker/>

Place the docker files in a dedicated directory like ~/InvenTree (i.e., mine is /home/rsutherland/git/InvenTree). This is where you’d typically clone the official InvenTree repository (git clone https://github.com/inventree/git/InvenTree.git ~/git/InvenTree) or create a working directory for your Docker setup. This keeps configuration files separate from data and aligns with standard InvenTree Docker practices.

```bash
cd ~
git clone https://github.com/inventree/InvenTree.git ~/git/InvenTree
```

Add samba provided HDD location (mounted at ~/samba) to docker-compose.yml to be used for backup.

```yaml
volumes:
  # ... other volumes ...
  - /home/rsutherland/samba/inventree-backup:/var/lib/inventree/backup
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

- Redo storage to mount the HDD on /srv/samba-share and serve it with Samba. Mount that share on /home/rsutherland/samba. This still won't fix the UID and GID problem when a Windows computer uses the share. This problem gets right to the heart of system administration, which isn't my area of expertise.

- The host name, "inventree.local," has an issue of locking up at somewhat random times. It seems to be temperature dependent. It is currently running Windows with some stress tests to see if the problem duplicates. The machine is an HP Pavilion from 2017 or 2018 with an 8-core AMD (1700, Zen 1) processor. I could not figure out how to update the BIOS with Linux, so I put Windows 10 back on it to do that. It has a TPM chip, but Windows 11 does not support the AMD 1700 processor, which seems odd. It's a second-hand computer, so there are no worries about it. Looking at the HP forums, it seems they got themselves into trouble with this product line. They appear to have pushed an AMI F.57 update that caused all sorts of issues. The version I installed, AMI F.60, was released years later. The lesson seems to be that if you are going to do automated installs, this stuff needs to be well-tested. It might be better to let customers do manual BIOS updates; we just need a way to do that in Linux. Anyway, the BIOS is updated, but now I am running some stress tests in Windows 10 to see if it locks up before putting Linux back on it.

- The host name, "inventree2.local," is an older machine but should allow progress until the issue with the other is sorted. 
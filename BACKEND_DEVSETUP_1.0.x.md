# Inventree 1.0.x Developer mode on Ubuntu 24.04

This guide will help you Install Inventree 1.0.x in Developer mode on Ubuntu 24.04 (<http://inventree2.local>). In Dev mode media content is served directly from a Django webserver so that changes can be looked at in real time, but this is not considered safe for production.

- ToDo: https is not working.

## Prerequisite Docker

To install Docker on Ubuntu 24.04 desktop, first update the apt package index to use the official Docker repository (in ca-certificates) to allow apt to use a repository over HTTPS

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
# the latest atm is 28.4.0
sudo docker container ls
# That should tell you what is going to stop, and this will stop the current Docker.
service docker.socket stop
service docker stop
sudo apt-get purge docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo rm -rf /var/lib/docker
sudo rm -rf /var/lib/containerd
```

Ubuntu (apt) will update these packages the normal way.

## Prerequisite Database Storage and Backup

The computer I have to run this on has an NVM which has two mounts one for the root and the other for Linux EFI images. It also has a HDD. I was thinking of puting the PostgreSQL storage on the HDD but that will make Inventree slow, it would be better to use the HDD for backups, and just operate out of the NVM/SSD.

```bash
# place working database on fast NVM/SSD e.g., in the .env file set INVENTREE_EXT_VOLUME=/homer/sutherland/inventree-data
mkdir -p ~/inventree-data
# set permissions for inventree docker container's internal user (UID/GID 1000:1000)
sudo chown -R 1000:1000 ~/inventree-data
sudo chmod -R 755 ~/inventree-data
# Make a mount ponit for the HDD (dev/sda on my setup), it needs chown -R 1000:1000 as well after HDD automount is setup.
sudo mkdir /srv/samba-share

# instructions for seting up the partition on /dev/sda is not provided here (I used gparted.), but the automount is.
cat /etc/fstab
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

Use an editor to add the HDD mount to to the end of fstab

```bash
sudo nano /etc/fstab
```

```text
/dev/sda1 /srv/samba-share auto defaults,nofail 0 0
```

```bash
# next prep systemd and mount it then set premissions (note systemctl will not mount the drive)
sudo systemctl daemon-reload
sudo mount /srv/samba-share
sudo chown -R 1000:1000 /srv/samba-share
# Create the backup subdirectory and set premissions for containers to use
sudo mkdir -p /srv/samba-share/inventree-backup
sudo chown -R 1000:1000 /srv/samba-share/inventree-backup
# install samba if not done
sudo apt-get install samba cifs-utils samba-common
# Add and set passwd for user in Samba
sudo smbpasswd -a rsutherland
# remove user with `sudo smbpasswd -x rsutherland`
# on power shell you can list all credentials with `net use` and delete with `net use \\inventree\IPC$ /delete`
# or `net use Y: /delete` but at the end of the day sometimes cached network credentials have to time out.

# [optional:] use samba to make the backup visabl and mounted to this location
mkdir -p ~/samba
sudo nano /etc/samba/smb.conf
```

Samba is serving the HDD mount. It forces all files created to be owned by 1000:1000 on the server, matching the system admin account that the InvenTree container uses. No client-side UID/GID config is needed in Windows or Linux, just map the drive with the credential(s) for valid users.

```conf
# modify the workgroup to reduce confusion for the Credential Manager 
# otherwise the full username ends up in a namespace as `MicrosoftAccount\rsutherland` that is causing me problems
[global]
workgroup = DEV-INVENTREE
# add this to the very end of the /etc/samba/smb.conf file
[Samba-Inventree]
comment = Inventree Data Share
path = /srv/samba-share
browsable = yes
read only = no
guest ok = no
create mask = 0775
directory mask = 0775
valid users = rsutherland  # the full user name is `INVENTREE\rustherland`
force user = rsutherland   # Forces ownership to UID 1000 (the first user made e.g., the admin user)
force group = rsutherland  # Forces ownership to GID 1000 (I used rsutherland when installing Ubuntu)
```

```bash
# restart samba
sudo service smbd restart
# Check for errors
testparm
# Windows can mount \\inventree2\Samba-Inventree with credentials (and so can Linux)
```

The Samba share can be mounted on the local system, and will work simular to how it does from Windows. To delay mounting the CIFS share, you can use the noauto and x-systemd.automount options in your /etc/fstab entry. This will prevent the system from mounting the share at boot and instead use systemd to automatically mount it when it is first accessed. Example /etc/fstab entry:

```bash
# use an editor to mount the cifs device (note the direction of // used on Linux)
sudo nano /etc/fstab
```

```conf
//dev-inventree/Samba-Inventree /home/rsutherland/samba cifs credentials=/etc/samba/samba_credentials.conf,noauto,x-systemd.automount,uid=1000,gid=1000,file_mode=0664,dir_mode=0775 0 0
```

Create a file to store your credentials. A good location is in a secure system location. E.g., /etc/samba/samba_credentials.conf for a system-wide mount.

```bash
# use an editor to add the mount to the end of fstab
sudo nano /etc/samba/samba_credentials.conf
```

```conf
username=rsutherland
password=your_password
```

```bash
# save and then secure so only the root user can look at it
sudo chmod 600 /etc/samba/samba_credentials.conf
# next restart things (how many differet ways are available?)
sudo systemctl restart smbd nmbd
sudo systemctl daemon-reload
# systemd automatically translates the mount point path (/home/rsutherland/samba) into the unit name (home-rsutherland-samba.mount). For the automount unit, it appends .automount to the name.
sudo systemctl start home-rsutherland-samba.automount
# check samba logs
sudo journalctl -u smbd
# with the HDD mounted create the backup volume
mkdir -p ~/samba/inventree-backup
# the samba mount will force the uid and gid to be what the container is happy with
```

## 1. Install Inventree's Docker Backend Files for development

### a. Clone from Github

- <https://docs.inventree.org/en/stable/develop/contributing/>

```bash
cd ~
mkdir ~/git
cd ~/git
git clone --branch stable https://github.com/inventree/InvenTree.git ~/git/InvenTree
cd ~/git/InvenTree
# Do not change docker.dev.env, for me that caused issues.
docker compose --project-directory . -f contrib/container/dev-docker-compose.yml run --rm inventree-dev-server invoke install
docker compose --project-directory . -f contrib/container/dev-docker-compose.yml run --rm inventree-dev-server invoke dev.setup-test --dev
```

### e. Start Containers

```bash
cd ~/git/InvenTree/
docker compose --project-directory . -f contrib/container/dev-docker-compose.yml up -d
# WIP: I get error INVE-E1 (https://docs.inventree.org/en/stable/settings/error_codes/#inve-e1)
```

### f. Stop Containers

```bash
cd ~/git/InvenTree/
sudo docker compose --project-directory . -f contrib/container/dev-docker-compose.yml down
# check logs
sudo docker compose --project-directory . -f contrib/container/dev-docker-compose.yml logs
```

### f. Nuke Containers

Development progresses in stages, from time to time a fresh install is needed.

```bash
cd ~/git/InvenTree/
# Removes associated volumes, including PostgreSQL data, to ensure a clean start
sudo docker compose --project-directory . -f contrib/container/dev-docker-compose.yml down --volumes --rmi all --remove-orphans
sudo docker system prune
# Dev should run out of the github folder so no need to clear the persistent folders, such as caddy,data,media,pgdata,static to avoid conflicts:
# sudo rm -rf ~/inventree-data/{caddy,data,media,pgdata,static}
# probably should update InvenTree repository so the local repo has the latest files
cd ~/git/InvenTree
git pull
```

# Inventree 1.0.x on Ubuntu 25.04

This guide will help you Install Inventree 1.0.x on Ubuntu 25.04 (<https://inventree.local>).

- ToDo: https is not working next step is to fix that.

## Prerequisite Docker

To install Docker on Ubuntu 25.04 desktop, first update the apt package index to use the official Docker repository (in ca-certificates) to allow apt to use a repository over HTTPS

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
# mkdir -p ~/inventree-data/{pgdata,data,media,static,caddy}
mkdir -p ~/inventree-data
# set permissions for inventree docker containerâ€™s internal user (UID/GID 1000:1000)
sudo chown -R 1000:1000 ~/inventree-data
sudo chmod -R 755 ~/inventree-data
# For me Caddy needed a custom container to use the system admin (UID/GID 1000:1000), more on that latter.
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
workgroup = INVENTREE
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

The Samba share can be mounted on the local system, and will work simular to how it does from Windows. To delay mounting the CIFS share, you can use the noauto and x-systemd.automount options in your /etc/fstab entry. This will prevent the system from mounting the share at boot and instead use systemd to automatically mount it when it is first accessed. Example /etc/fstab entry assuming gid and uid are 1000:

```bash
# use an editor to mount the cifs device (note the direction of // used on Linux)
sudo nano /etc/fstab
```

```conf
//inventree/Samba-Inventree /home/rsutherland/samba cifs credentials=/etc/samba/samba_credentials.conf,noauto,x-systemd.automount,uid=1000,gid=1000,file_mode=0664,dir_mode=0775 0 0
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

## 1. Install Inventree's Docker Backend Files

### a. Clone from Github

```bash
cd ~
mkdir ~/git
git clone --branch stable https://github.com/inventree/InvenTree.git ~/git/InvenTree
```

Docker packages will lag Github a little, just make sure the tag you are using is available

- <https://hub.docker.com/r/inventree/inventree/tags>
- <https://docs.inventree.org/en/stable/releases/release_notes/#stable-branch>

### b. Update the .env file

```bash
cd ~/git/InvenTree/contrib/container/
nano .env
```

```conf
# ...
# InvenTree server URL - update this to match your server URL.
INVENTREE_SITE_URL="http://inventree.local"
# ...
# InvenTree superuser account details
# Un-comment (and complete) these lines to auto-create an admin account
INVENTREE_ADMIN_USER=admin  #<<<change_me
INVENTREE_ADMIN_PASSWORD=lol123ok!  #<<<change_me @GitGuardian this is on your Banned Lists so do not bitch about it as an example
INVENTREE_ADMIN_EMAIL=your_google_email@gmail.com

# email setup
INVENTREE_EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
INVENTREE_EMAIL_HOST=smtp.gmail.com
INVENTREE_EMAIL_PORT=587
INVENTREE_EMAIL_USERNAME=your_google_email@gmail.com
INVENTREE_EMAIL_PASSWORD=not-a-real-password  # @GitGuardian this is an example
INVENTREE_EMAIL_USE_TLS=False
INVENTREE_EMAIL_USE_SSL=True
INVENTREE_EMAIL_SENDER=your_google_email@gmail.com
# ...
# Database credentials !!!SHOULD BE!!! changed from the default values!
# ...
INVENTREE_DB_USER=pguser #<<<change_me
INVENTREE_DB_PASSWORD=not-a-real-password  # @GitGuardian this is an example
# ...
```

InvenTree requires email settings for notifications (e.g., user invites, alerts). Configure these in the `.env` file. I am going to use a gmail account.

Important:

- INVENTREE_EMAIL_HOST_PASSWORD: You cannot use your regular Google account password here. You must generate an App Password for InvenTree. This is a security measure required by Google to use third-party applications with your account. You can generate an App Password in your Google Account settings under "Security" and then "2-Step Verification". If you have Google Workspace (<https://workspace.google.com/lp/business/>) the admin account can not be used to generate an App Password.

- INVENTREE_EMAIL_HOST_USER and INVENTREE_EMAIL_SENDER: It's best practice to use the same email address for both of these variables.

- Understanding inventree-server Service Volumes: The Inventree containers will operate on data that is on a NVM (or SSD) at ~/inventree-data/{data,media,static,backup}. Host Path: The left side (e.g., ${INVENTREE_HOST_DATA_DIR}/data) is the directory on your Ubuntu host (e.g., /home/rsutherland/inventree-data/data). Container Path: The right side (e.g., /var/lib/inventree/data) is where the container accesses the data inside its filesystem. Inside the Container: When InvenTree runs invoke backup, it writes backup files (e.g., DB dumps, media archives) to /var/lib/inventree/backup. Docker’s volume mapping ensures these files appear on the host at /srv/samba-share/inventree-backup, accessible via Samba (\\inventree2\Samba-Inventree\inventree-backup).

### c. mDNS Setup (not needed, remove after more testing)

```bash
sudo apt update
sudo apt install avahi-daemon
sudo systemctl enable avahi-daemon
sudo systemctl start avahi-daemon
sudo nano /etc/avahi/services/inventree.service
```

```xml
<?xml version="1.0" standalone='no'?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group>
    <name>InvenTree</name>
    <service>
        <type>_http._tcp</type>
        <port>80</port>
        <host-name>inventree.local</host-name>
    </service>
</service-group>
```

```bash
sudo systemctl restart avahi-daemon
```

### d. Compose container is used to setup the Databse

```bash
cd ~/git/InvenTree/contrib/container/
# with .env set up init the database
sudo docker compose run --rm inventree-server invoke update
```

### e. Start Containers

```bash
sudo docker compose up -d
curl -v -L http://inventree.local
```

### f. Stop Containers

```bash
sudo docker compose down
```

### g. Nuke Containers

Development progresses in stages, from time to time a fresh install is needed.

```bash
cd ~/git/InvenTree/contrib/container
# Removes associated volumes, including PostgreSQL data, to ensure a clean start
sudo docker compose down --volumes --rmi all --remove-orphans
sudo docker system prune
# Clear the persistent folders [caddy|data|media|pgdata|static|***backup***] to avoid conflicts:
sudo rm -rf ~/inventree-data
# probably should update InvenTree repository so the local repo has the latest files
cd ~/git/InvenTree
git pull
```

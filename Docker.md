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
rsutherland@inventree2:~$ mkdir -p ~/inventree-data/{pgdata,data,media,static}
# set permissions for inventree docker container’s internal user (UID/GID 1000)
rsutherland@inventree2:~$ sudo chown -R 1000:1000 ~/inventree-data
# make a mount ponit for the HDD (dev/sda on my setup), it needs chown -R 1000:1000 as well after HDD automount is setup.
rsutherland@inventree2:~$ sudo mkdir /srv/samba-share

# instructions for seting up the partition is not provided here (I used gparted.)
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

Use an editor to add the HDD mount to to the end of fstab

```bash
rsutherland@inventree2:~$ sudo nano /etc/fstab
```

```
/dev/sda1 /srv/samba-share auto defaults,nofail 0 0
```

```bash
# next mount it and set premission.
rsutherland@inventree2:~$ systemctl daemon-reload
rsutherland@inventree2:~$ sudo chown -R 1000:1000 /srv/samba-share
# Create the backup subdirectory and set premissions for containers to use
rsutherland@inventree2:~$ sudo mkdir -p /srv/samba-share/inventree_backup
rsutherland@inventree2:~$ sudo chown -R 1000:1000 /srv/samba-share/inventree_backup
# install samba if not done
rsutherland@inventree2:~$ sudo apt-get install samba cifs-utils samba-common
# Set passwd for your user in Samba:
rsutherland@inventree2:~$ sudo smbpasswd -a rsutherland

# [optional:] use samba to make the backup visabl and mounted to this location
rsutherland@inventree2:~$ mkdir -p ~/samba
rsutherland@inventree2:~$ sudo nano /etc/samba/smb.conf
```

Note that samba is serving the HDD mount. This forces all files created via Samba (e.g., from Windows) to be owned by 1000:1000 on the server, matching the InvenTree container user. No client-side UID/GID config needed—Windows users just map the drive with credentials.

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
force user = rsutherland   # Forces ownership to UID 1000 (the first user made e.g., the admin user)
force group = rsutherland  # Forces ownership to GID 1000 (I used rsutherland when installing Ubuntu)
```

```bash
# restart samba
rsutherland@inventree2:~$ sudo service smbd restart
# Check for errors
rsutherland@inventree2:~$ testparm
# Windows can mount \\inventree2\Samba-Inventree with credentials (and so can Linux)
```

The Samba share can be mounted on the local system, and will work simular to how it does from Windows. To delay mounting the CIFS share, you can use the noauto and x-systemd.automount options in your /etc/fstab entry. This will prevent the system from mounting the share at boot and instead use systemd to automatically mount it when it is first accessed. Example /etc/fstab entry:

```bash
# use an editor to mount the cifs device (note the direction of // used on Linux)
rsutherland@inventree2:~$ sudo nano /etc/fstab
```

```conf
//inventree2/Samba-Inventree /home/rsutherland/samba cifs credentials=/etc/samba/samba_credentials.conf,noauto,x-systemd.automount 0 0
```

Create a file to store your credentials. A good location is in a secure system location. E.g., /etc/samba/samba_credentials.conf for a system-wide mount.

```bash
# use an editor to add the mount to to the end of fstab
rsutherland@inventree2:~$ sudo nano /etc/samba/samba_credentials.conf
```

```conf
username=rsutherland
password=your_password
```

```bash
# save and then secure so only the root user can look at it
rsutherland@inventree2:~$ sudo chmod 600 /etc/samba/samba_credentials.conf
# next restart things (how many differet ways are available?)
rsutherland@inventree2:~$ sudo systemctl restart smbd nmbd
rsutherland@inventree2:~$ sudo systemctl daemon-reload
# systemd automatically translates the mount point path (/home/rsutherland/samba) into the unit name (home-rsutherland-samba.mount). For the automount unit, it appends .automount to the name.
rsutherland@inventree2:~$ sudo systemctl start home-rsutherland-samba.automount
# check samba logs
rsutherland@inventree2:~$ sudo journalctl -u smbd
# with the HDD mounted create the backup volume
rsutherland@inventree2:~$ mkdir -p ~/samba/inventree-backup
# the samba mount will force the uid and gid to be what the container is happy with
```

## Install Inventree's Docker packages

These notes are for my setup, for your own it is better to use the ones Inventree provides.

<https://docs.inventree.org/en/stable/start/docker/>

Place the docker files in a dedicated directory like ~/git/InvenTree. This keeps configuration files separate from data and aligns with standard InvenTree Docker practices.

```bash
rsutherland@inventree2:~$ cd ~
rsutherland@inventree2:~$ git clone --branch stable https://github.com/inventree/InvenTree.git ~/git/InvenTree
```

Change the .env file (note that it is a hidden file by convinsion on Linux) to match the setup. Ensure .env includes required database variables (INVENTREE_DB_USER, INVENTREE_DB_PASSWORD, INVENTREE_DB_NAME). 

```bash
cd ~/git/InvenTree/contrib/container/
nano .env
# best to limit who can see this, sadly we can't make it root only.
chmod 600 .env
```

```conf
# ...
# InvenTree server URL - update this to match your server URL.
#INVENTREE_SITE_URL="http://inventree2.local"
INVENTREE_SITE_URL="http://192.168.4.39"  # You can specify a local IP address here
#INVENTREE_SITE_URL="https://inventree.my-domain.com"  # Or a public domain name (which you control)

# Specify the location of the external data volume
# By default, placed in local directory 'inventree-data'
# INVENTREE_EXT_VOLUME=./inventree-data
# the defult above might work if I had named the first user inventree... ¯\_(ツ)_/¯
INVENTREE_HOST_DATA_DIR=/home/rsutherland/inventree-data
# ...
# Database configuration options
# DO NOT CHANGE THESE SETTINGS (unless you really know what you are doing)
INVENTREE_DB_ENGINE=postgresql
INVENTREE_DB_NAME=inventree
INVENTREE_DB_HOST=inventree-db
INVENTREE_DB_PORT=5432

# Database credentials - These !!!SHOULD BE!!! changed from the default values!
# Note: These are *NOT* the InvenTree server login credentials,
#       they are the credentials for the PostgreSQL database
INVENTREE_DB_USER=pguser_<<<change_me
INVENTREE_DB_PASSWORD=your_secret
# ...
```

InvenTree requires email settings for notifications (e.g., user invites, alerts). Configure these in the `.env` file. I am going to use a gmail account.

```conf
INVENTREE_EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
INVENTREE_EMAIL_HOST=smtp.gmail.com
INVENTREE_EMAIL_PORT=587
INVENTREE_EMAIL_HOST_USER=your_google_email@gmail.com
INVENTREE_EMAIL_HOST_PASSWORD=your_app_password
INVENTREE_EMAIL_USE_TLS=True
INVENTREE_EMAIL_SENDER=your_google_email@gmail.com
```

Important:

- INVENTREE_EMAIL_HOST_PASSWORD: You cannot use your regular Google account password here. You must generate an App Password for InvenTree. This is a security measure required by Google to use third-party applications with your account. You can generate an App Password in your Google Account settings under "Security" and then "2-Step Verification". If you have Google Workspace (<https://workspace.google.com/lp/business/>) the admin account can not be used to generate an App Password.

- INVENTREE_EMAIL_HOST_USER and INVENTREE_EMAIL_SENDER: It's best practice to use the same email address for both of these variables.

Next the docker-compose.yml needs setup for Ubuntu 24.04 (use an expert, I used Grok.) 

Edit docker-compose.yml. The :z in the InvenTree example (- ${INVENTREE_EXT_VOLUME}:/home/inventree/data:z) is a Docker volume mount option related to SELinux (Security-Enhanced Linux), which is common on Red Hat-based systems (e.g., CentOS, Fedora) but typically not enabled on Ubuntu 24.04 by default. Service inventree-cache doesn’t need volumes unless persistent Redis data is desired.

```bash
cd ~/git/InvenTree/contrib/container/
nano docker-compose.yml
```

```yaml
services:
  inventree-db:
    image: postgres:13
    container_name: inventree-db
    expose:
      - ${INVENTREE_DB_PORT:-5432}/tcp
    environment:
      - PGDATA=/var/lib/postgresql/data/pgdb
      - POSTGRES_USER=${INVENTREE_DB_USER}
      - POSTGRES_PASSWORD=${INVENTREE_DB_PASSWORD}
      - POSTGRES_DB=${INVENTREE_DB_NAME}
    volumes:
      - ${INVENTREE_HOST_DATA_DIR}/pgdata:/var/lib/postgresql/data
    restart: unless-stopped

  inventree-cache:
    image: redis:7.0
    container_name: inventree-cache
    env_file:
      - .env
    expose:
      - ${INVENTREE_CACHE_PORT:-6379}
    restart: always

  inventree-server:
    image: inventree/inventree:${INVENTREE_TAG:-stable}
    container_name: inventree-server
    expose:
      - 8000
    depends_on:
      - inventree-db
      - inventree-cache
    env_file:
      - .env
    volumes:
      - ${INVENTREE_HOST_DATA_DIR}/data:/home/inventree/data
      - ${INVENTREE_HOST_DATA_DIR}/media:/home/inventree/data/media
      - ${INVENTREE_HOST_DATA_DIR}/static:/home/inventree/data/static
      - /srv/samba-share/inventree-backup:/home/inventree/data/backup
    restart: unless-stopped

  inventree-worker:
    image: inventree/inventree:${INVENTREE_TAG:-stable}
    container_name: inventree-worker
    command: invoke worker
    depends_on:
      - inventree-server
    env_file:
      - .env
    volumes:
      - ${INVENTREE_HOST_DATA_DIR}/data:/home/inventree/data
      - ${INVENTREE_HOST_DATA_DIR}/media:/home/inventree/data/media
      - /srv/samba-share/inventree-backup:/home/inventree/data/backup
    restart: unless-stopped

  inventree-proxy:
    container_name: inventree-proxy
    image: caddy:alpine
    restart: always
    depends_on:
      - inventree-server
    ports:
      - ${INVENTREE_WEB_PORT:-80}:80
      - 443:443
    env_file:
      - .env
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - ${INVENTREE_HOST_DATA_DIR}/static:/var/www/static
      - ${INVENTREE_HOST_DATA_DIR}/media:/var/www/media
```

Understanding inventree-server Service Volumes: The Inventree containers will operate on data that is on a NVM (or SSD) at ~/inventree-data/{data,media,static,backup}. Host Path: The left side (e.g., ${INVENTREE_HOST_DATA_DIR}/data) is the directory on your Ubuntu host (e.g., /home/rsutherland/inventree-data/data). Container Path: The right side (e.g., /var/lib/inventree/data) is where the container accesses the data inside its filesystem. Inside the Container: When InvenTree runs invoke backup, it writes backup files (e.g., DB dumps, media archives) to /var/lib/inventree/backup. Docker’s volume mapping ensures these files appear on the host at /srv/samba-share/inventree-backup, accessible via Samba (\\inventree2\Samba-Inventree\inventree-backup).

mDNS Setup

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
        <host-name>inventree2.local</host-name>
    </service>
</service-group>
```

```bash
sudo systemctl restart avahi-daemon
curl http://inventree2.local:80
```

Now run "docker compose" which will take some time.

```bash
rsutherland@inventree2:~$ cd ~/git/InvenTree/contrib/container/
# validate the config
rsutherland@inventree2:~$ docker compose config
# Pull Latest Docker Images
rsutherland@inventree2:~$ docker compose pull
# Start the InvenTree stack in detached mode:
rsutherland@inventree2:~$ docker compose up -d
# Ensure required Python packages are installed.
# Create a new (empty) database.
# Perform necessary schema updates to create database tables.
# Update translation and static files.
rsutherland@inventree2:~$ docker compose run --rm inventree-server invoke update
# bring up the containers (-d is detached mode)
rsutherland@inventree2:~$ docker compose up -d
# test pgsql
rsutherland@inventree2:~$ docker compose exec inventree-db psql -U inventree -d inventree -c "\l"
# Verify services are running
docker compose ps
# Look for database or permission errors
rsutherland@inventree2:~$ docker compose logs inventree-server inventree-db
# Test volume access
rsutherland@inventree2:~$ docker compose exec inventree-server ls -l /var/lib/inventree/{data,media,static,backup}
rsutherland@inventree2:~$ docker compose exec inventree-worker ls -l /var/lib/inventree/backup
rsutherland@inventree2:~$ docker compose exec inventree-db psql -U $INVENTREE_DB_USER -d $INVENTREE_DB_NAME -c "\l"
# Test with a backup run (later schedule it with cron). Restore with "docker compose exec inventree-server invoke restore".
rsutherland@inventree2:~$ docker compose exec inventree-server invoke backup
# there is no backup log? e.g., docker compose logs inventree-server | grep backup
# Since curl isn’t in caddy:alpine, use a temporary container:
rsutherland@inventree2:~$ docker run --rm --network inventree_default curlimages/curl curl http://inventree-server:8000
# Test e-mail
rsutherland@inventree2:~$ docker compose exec inventree-server invoke send-test-email
rsutherland@inventree2:~$ docker compose logs inventree-server | grep email
# To stop Inventree (this will presist until "docker compose up" is run again)
rsutherland@inventree2:~$ docker compose down
```

This has been progressing in stages, so when I need to step back.

```bash
rsutherland@inventree2:~$ cd ~/InvenTree_prod
# Removes associated volumes, including PostgreSQL data, to ensure a clean start
rsutherland@inventree2:~$ docker compose down --volumes --rmi all --remove-orphans
rsutherland@inventree2:~$ docker system prune
# Clear the persistent database data to avoid conflicts:
rsutherland@inventree2:~$ sudo rm -rf ~/inventree-docker/inventree-data
```

## To Do List

Notes to remind me what I am working on

- ALLOWED_HOSTS and CSRF_TRUSTED_ORIGINS setup for Ubuntu 24.04

Browsers show ERR_CONNECTION_REFUSED. Try to Run Django Dev Server on port 8000 to see error mesages. Problem is the Gunicorn processes keeps restarting, so this overrides the default entrypoint (/bin/ash ./init.sh) to run a shell and sleep forever, preventing Gunicorn from starting automatically. Update the inventree-server section as follows in this debug session. Two terminals are used and comments are added so you can tell when they are switched.

```bash
rsutherland@inventree2:~/git/InvenTree/contrib/container$ nano ~/git/InvenTree/contrib/container/docker-compose.yml
rsutherland@inventree2:~/git/InvenTree/contrib/container$ cat ~/git/InvenTree/contrib/container/docker-compose.yml
services:
  inventree-db:
    image: postgres:13
    container_name: inventree-db
    expose:
      - ${INVENTREE_DB_PORT:-5432}/tcp
    environment:
      - PGDATA=/var/lib/postgresql/data/pgdb
      - POSTGRES_USER=${INVENTREE_DB_USER}
      - POSTGRES_PASSWORD=${INVENTREE_DB_PASSWORD}
      - POSTGRES_DB=${INVENTREE_DB_NAME}
    volumes:
      - ${INVENTREE_HOST_DATA_DIR}/pgdata:/var/lib/postgresql/data
    restart: unless-stopped
  inventree-cache:
    image: redis:7.0
    container_name: inventree-cache
    env_file:
      - .env
    expose:
      - ${INVENTREE_CACHE_PORT:-6379}
    restart: always
  inventree-server:
    image: inventree/inventree:${INVENTREE_TAG:-stable}
    container_name: inventree-server
    entrypoint: /bin/ash
    command: -c "sleep infinity" # Keeps the container running without starting Gunicorn
    expose:
      - 8000
    depends_on:
      - inventree-db
      - inventree-cache
    env_file:
      - .env
    volumes:
      - ${INVENTREE_HOST_DATA_DIR}/data:/home/inventree/data
      - ${INVENTREE_HOST_DATA_DIR}/media:/home/inventree/data/media
      - ${INVENTREE_HOST_DATA_DIR}/static:/home/inventree/data/static
      - /srv/samba-share/inventree-backup:/home/inventree/data/backup
# restart: unless-stopped # Temporarily disabled
  inventree-worker:
    image: inventree/inventree:${INVENTREE_TAG:-stable}
    container_name: inventree-worker
    command: invoke worker
    depends_on:
      - inventree-server
    env_file:
      - .env
    volumes:
      - ${INVENTREE_HOST_DATA_DIR}/data:/home/inventree/data
      - ${INVENTREE_HOST_DATA_DIR}/media:/home/inventree/data/media
      - /srv/samba-share/inventree-backup:/home/inventree/data/backup
    restart: unless-stopped
  inventree-proxy:
    container_name: inventree-proxy
    image: caddy:alpine
    restart: always
    depends_on:
      - inventree-server
    ports:
      - ${INVENTREE_WEB_PORT:-80}:80
      - 443:443
    env_file:
      - .env
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - ${INVENTREE_HOST_DATA_DIR}/static:/var/www/static
      - ${INVENTREE_HOST_DATA_DIR}/media:/var/www/media
rsutherland@inventree2:~/git/InvenTree/contrib/container$ docker compose down
[+] Running 6/6
 ? Container inventree-proxy Removed 0.2s
 ? Container inventree-worker Removed 10.2s
 ? Container inventree-server Removed 2.4s
 ? Container inventree-cache Removed 0.2s
 ? Container inventree-db Removed 0.1s
 ? Network inventree_default Removed 0.2s
rsutherland@inventree2:~/git/InvenTree/contrib/container$ docker compose up -d inventree-server
[+] Running 4/4
 ? Network inventree_default Created 0.0s
 ? Container inventree-db Started 0.3s
 ? Container inventree-cache Started 0.3s
 ? Container inventree-server Started 0.4s
rsutherland@inventree2:~/git/InvenTree/contrib/container$ docker compose exec inventree-server ps aux | grep gunicorn
rsutherland@inventree2:~/git/InvenTree/contrib/container$ docker compose exec inventree-server netstat -tuln | grep 8000
rsutherland@inventree2:~/git/InvenTree/contrib/container$ docker compose exec -w /home/inventree/src/backend/InvenTree inventree-server gunicorn --bind 0.0.0.0:8000 InvenTree.wsgi:application
Python version 3.11.9 - /usr/local/bin/python
/root/.local/lib/python3.11/site-packages/allauth/exceptions.py:9: UserWarning: allauth.exceptions is deprecated, use allauth.core.exceptions
  warnings.warn("allauth.exceptions is deprecated, use allauth.core.exceptions")
[2025-08-12 00:41:11 +0000] [19] [INFO] Starting gunicorn 23.0.0
[2025-08-12 00:41:11 +0000] [19] [INFO] Listening at: http://0.0.0.0:8000 (19)
[2025-08-12 00:41:11 +0000] [19] [INFO] Using worker: sync
[2025-08-12 00:41:11 +0000] [61] [INFO] Booting worker with pid: 61
[2025-08-12 00:41:11 +0000] [62] [INFO] Booting worker with pid: 62
[2025-08-12 00:41:11 +0000] [63] [INFO] Booting worker with pid: 63
[2025-08-12 00:41:11 +0000] [64] [INFO] Booting worker with pid: 64
[2025-08-12 00:41:11 +0000] [65] [INFO] Booting worker with pid: 65
[2025-08-12 00:41:11 +0000] [66] [INFO] Booting worker with pid: 66
[2025-08-12 00:41:11 +0000] [67] [INFO] Booting worker with pid: 67
[2025-08-12 00:41:12 +0000] [68] [INFO] Booting worker with pid: 68
[2025-08-12 00:41:12 +0000] [69] [INFO] Booting worker with pid: 69
rsutherland@inventree2:~/git/InvenTree/contrib/container$ # switching from the Django Dev WSGI Server to the other terminal
rsutherland@inventree2:~/git/InvenTree/contrib/container$ docker run --rm --network inventree_default curlimages/curl curl -L http://inventree-server:8000
  % Total % Received % Xferd Average Speed Time Time Time Current
                                 Dload Upload Total Spent Left Speed
  0 0 0 0 0 0 0 0 --:--:-- --:--:-- --:--:-- 0
<!doctype html>
<html lang="en">
<head>
  <title>Bad Request (400)</title>
</head>
<body>
  <h1>Bad Request (400)</h1><p></p>
</body>
</html>
100 143 0 143 0 0 1546 0 --:--:-- --:--:-- --:--:-- 1554
rsutherland@inventree2:~/git/InvenTree/contrib/container$ # switching back to the Django Dev WSGI Server terminal, repeating the command to keep us grounded
rsutherland@inventree2:~/git/InvenTree/contrib/container$ docker compose exec -w /home/inventree/src/backend/InvenTree inventree-server gunicorn --bind 0.0.0.0:8000 InvenTree.wsgi:application
Python version 3.11.9 - /usr/local/bin/python
/root/.local/lib/python3.11/site-packages/allauth/exceptions.py:9: UserWarning: allauth.exceptions is deprecated, use allauth.core.exceptions
  warnings.warn("allauth.exceptions is deprecated, use allauth.core.exceptions")
[2025-08-12 00:41:11 +0000] [19] [INFO] Starting gunicorn 23.0.0
[2025-08-12 00:41:11 +0000] [19] [INFO] Listening at: http://0.0.0.0:8000 (19)
[2025-08-12 00:41:11 +0000] [19] [INFO] Using worker: sync
[2025-08-12 00:41:11 +0000] [61] [INFO] Booting worker with pid: 61
[2025-08-12 00:41:11 +0000] [62] [INFO] Booting worker with pid: 62
[2025-08-12 00:41:11 +0000] [63] [INFO] Booting worker with pid: 63
[2025-08-12 00:41:11 +0000] [64] [INFO] Booting worker with pid: 64
[2025-08-12 00:41:11 +0000] [65] [INFO] Booting worker with pid: 65
[2025-08-12 00:41:11 +0000] [66] [INFO] Booting worker with pid: 66
[2025-08-12 00:41:11 +0000] [67] [INFO] Booting worker with pid: 67
[2025-08-12 00:41:12 +0000] [68] [INFO] Booting worker with pid: 68
[2025-08-12 00:41:12 +0000] [69] [INFO] Booting worker with pid: 69
2025-08-12 00:41:58,581 ERROR Invalid HTTP_HOST header: 'inventree-server:8000'. You may need to add 'inventree-server' to ALLOWED_HOSTS.
Traceback (most recent call last):
  File "/root/.local/lib/python3.11/site-packages/django/core/handlers/exception.py", line 55, in inner
    response = get_response(request)
               ^^^^^^^^^^^^^^^^^^^^^
  File "/root/.local/lib/python3.11/site-packages/django/utils/deprecation.py", line 133, in __call__
    response = self.process_request(request)
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/root/.local/lib/python3.11/site-packages/django/middleware/common.py", line 48, in process_request
    host = request.get_host()
           ^^^^^^^^^^^^^^^^^^
  File "/root/.local/lib/python3.11/site-packages/django/http/request.py", line 150, in get_host
    raise DisallowedHost(msg)
django.core.exceptions.DisallowedHost: Invalid HTTP_HOST header: 'inventree-server:8000'. You may need to add 'inventree-server' to ALLOWED_HOSTS.
2025-08-12 00:41:58,661 WARNING Bad Request: /
```

The curl -L http://inventree-server:8000 returned a "Bad Request (400)" with a DisallowedHost error (Invalid HTTP_HOST header: 'inventree-server:8000') shows that the inventree-server is responding, the issue is that: Django’s ALLOWED_HOSTS needs to include inventree-server for internal Docker network requests. This explains the empty responses and ERR_CONNECTION_REFUSED in browsers, as Caddy’s proxy requests to inventree-server:8000 are being rejected. The Gunicorn processes are no longer restarting automatically thanks to the entrypoint: /bin/ash and command: -c "sleep infinity" in docker-compose.yml, and port 8000 is free when we need it.

Gunicorn: Started successfully with gunicorn --bind 0.0.0.0:8000 InvenTree.wsgi:application in /home/inventree/src/backend/InvenTree, but rejected requests due to ALLOWED_HOSTS. ALLOWED_HOSTS: Missing inventree-server (Docker service name used internally).

```bash
rsutherland@inventree2:~/git/InvenTree/contrib/container$ docker compose exec -w /home/inventree/src/backend/InvenTree inventree-server python manage.py shell
Python version 3.11.9 - /usr/local/bin/python
/root/.local/lib/python3.11/site-packages/allauth/exceptions.py:9: UserWarning: allauth.exceptions is deprecated, use allauth.core.exceptions
  warnings.warn("allauth.exceptions is deprecated, use allauth.core.exceptions")
Python 3.11.9 (main, Apr  4 2024, 00:51:37) [GCC 12.2.1 20220924] on linux
Type "help", "copyright", "credits" or "license" for more information.
(InteractiveConsole)
>>> from django.conf import settings
>>> print(settings.ALLOWED_HOSTS)
['*', '192.168.4.39']
>>> print(settings.CSRF_TRUSTED_ORIGINS)
['http://192.168.4.39']
>>> exit()
rsutherland@inventree2:~/git/InvenTree/contrib/container$ # Add inventree-server pluse anything else you want to work
rsutherland@inventree2:~/git/InvenTree/contrib/container$ # ALLOWED_HOSTS defines a list of host/domain names that the web application is allowed to serve
rsutherland@inventree2:~/git/InvenTree/contrib/container$ # ACSRF_TRUSTED_ORIGINS defines a list of trusted origins from which "unsafe" requests (e.g., POST, PUT, DELETE) are allowed to originate
rsutherland@inventree2:~/git/InvenTree/contrib/container$ nano /home/rsutherland/inventree-data/data/config.yaml
```

update config.yaml

```yaml
allowed_hosts:
  - 'inventree-server'
  - '192.168.4.39'
  - 'inventree2.local'
trusted_origins:
  - 'http://192.168.4.39'
  - 'http://inventree2.local'
  - 'http://localhost'
  - 'http://*.local'
```

I want to be able to use the API to update inventory from local computers.

- In a standard InvenTree Docker installation, a separate container (often called inventree-proxy) runs a web server like Caddy. This proxy container is responsible for: Serving the static files directly from a mounted volume, and Reverse-proxying other requests to the InvenTree Django server. The inventree-proxy container needs to be able to access the static files. If static_root is commented out, Django doesn't know where to put the files, and the inventree-proxy can't find them, leading to the broken web interface. I seem to have caused this with a missing line in the .env file for setting up the docker containers... now I need to fix it. Uncomment the "static_root" line in ~/inventree-data/data/config.yaml then run collectstatic. Question is do I comment out "static_root" after doing this, probably so.

```bash
cd ~/git/InvenTree/contrib/container
docker compose down
# Uncomment the "static_root" line in ~/inventree-data/data/config.yaml
sudo nano /home/rsutherland/inventree-data/data/config.yaml
docker compose up -d
# docker compose run --rm inventree-server invoke collectstatic
docker compose exec inventree-server python /home/inventree/src/backend/InvenTree/manage.py collectstatic --noinput
# [optional] comment them back out for security then restart
docker compose down
docker compose up -d
```

- (done) Redo storage to mount the HDD on /srv/samba-share and serve it with Samba. Ensure it’s owned by UID/GID 1000:1000 (e.g., the first user created at system install). Samba can Force ownership to the UID and GID for any Windows computer that uses the share.

- (wip) The host name, "inventree.local," has an issue of locking up at somewhat random times. It seems to be temperature dependent. It is currently running Windows with some stress tests to see if the problem duplicates. The machine is an HP Pavilion from 2017 or 2018 with an 8-core AMD (1700, Zen 1) processor. I could not figure out how to update the BIOS with Linux, so I put Windows 10 back on it to do that. It has a TPM chip, but Windows 11 does not support the AMD 1700 processor, which seems odd. It's a second-hand computer, so there are no worries about it. Looking at the HP forums, it seems they got themselves into trouble with this product line. They appear to have pushed an AMI F.57 update that caused all sorts of issues. The version I installed, AMI F.60, was released years later. The lesson seems to be that if you are going to do automated installs, this stuff needs to be well-tested. It might be better to let customers do manual BIOS updates; we just need a way to do that in Linux. Anyway, the BIOS is updated, I run some stress tests in Windows 10 and did not see a lock up. Now I am runing some test with Ubuntu 24.04 to see if it will lock up and it did around 24 hours. So now I have put Ubuntu 20.04 on it and will let it run while keeping an eye out for a lock up. The dmesg command shows a lot of issues with this version (mostly ACPI). I wonder if the newer version is twidling somthing that it should not, efectivly a Time To Live (TTL) timer. 

- The host name, "inventree2.local," is an older machine but should allow progress until the issue with the other is sorted. This Acer machine has no errors reported with dmesg running Ubuntu 24.04.
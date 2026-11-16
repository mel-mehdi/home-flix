# HomeFlix on an Oracle Cloud free server

The server runs HomeFlix and the Cloudflare tunnel day and night, so your PC can be off.
The link is still a free `trycloudflare.com` link: it changes only when the server or the tunnel restarts.

## 1. Create the Oracle account (you, about 15 minutes)

1. Sign up at https://signup.cloud.oracle.com.
   - You need a phone number and a real credit or debit card. The card is checked but not charged on the free tier. Prepaid and virtual cards are usually refused.
   - **Home region**: pick one close to Morocco, for example *Spain Central (Madrid)* or *France South (Marseille)*. It can't be changed later.
2. Wait for the "account ready" e-mail, then sign in.

## 2. Create the server

In the Oracle console: **Compute → Instances → Create instance**.

| Setting | Choose |
|---|---|
| Name | `homeflix` |
| Image | **Canonical Ubuntu 24.04** |
| Shape | **Ampere → VM.Standard.A1.Flex**, 1 OCPU, 6 GB memory |
| Networking | Keep the defaults; make sure **Assign a public IPv4 address** is on |
| SSH keys | **Generate a key pair for me** → **Save private key** |

- Save the private key as `C:\Users\melme\.ssh\oracle-homeflix.key`.
- If you get **"Out of capacity"**: try another *availability domain* on the same page, try again later, or pick the shape **VM.Standard.E2.1.Micro** (AMD, also free; slower, 1 GB memory — the setup adds swap for it).
- When it says **Running**, copy the **Public IP address** from the instance page.

No firewall ports need opening: visitors reach HomeFlix through the Cloudflare tunnel.

## 3. Upload HomeFlix (PowerShell on the PC, in the HomeFlix folder)

```powershell
# Pack the code and a clean copy of the database (your .env is not included)
powershell -ExecutionPolicy Bypass -File .\deploy\make-bundle.ps1

$key = "$env:USERPROFILE\.ssh\oracle-homeflix.key"
$server = "ubuntu@PUBLIC_IP"     # replace PUBLIC_IP

# Windows' ssh refuses a key that other accounts can read
icacls $key /inheritance:r /grant:r "${env:USERNAME}:R"

scp -i $key homeflix-bundle.tgz "${server}:~/"
scp -i $key .env "${server}:~/homeflix.env"
ssh -i $key $server
```

## 4. Set up the server (in the ssh window)

```bash
mkdir -p homeflix && tar -xzf homeflix-bundle.tgz -C homeflix
mv homeflix.env homeflix/.env && chmod 600 homeflix/.env
sudo bash homeflix/deploy/oracle-setup.sh
```

It takes 3 to 10 minutes and ends with `HomeFlix is online: https://….trycloudflare.com`.
Sign in with your usual HomeFlix username and password: your accounts and My List came with the database.

**See the link again later** (from the PC):

```powershell
ssh -i "$env:USERPROFILE\.ssh\oracle-homeflix.key" ubuntu@PUBLIC_IP homeflix-link
```

## 5. Turn off the PC copy

Otherwise there are two HomeFlix sites with different data.

1. Delete the shortcut **HomeFlix link** from the Startup folder (Win+R → `shell:startup`).
2. Stop the PC's tunnel in Task Manager (`cloudflared.exe`) and HomeFlix in Docker Desktop.

## Updating the server later

From now on the server's database is the real one. An update replaces the code but **keeps the server's database**:

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\make-bundle.ps1
scp -i $key homeflix-bundle.tgz "${server}:~/"
ssh -i $key $server "tar -xzf homeflix-bundle.tgz -C homeflix --exclude=./homeflix.db && sudo bash homeflix/deploy/oracle-setup.sh"
```

## Things to know

- Oracle's free tier page says idle Always Free servers can be reclaimed. Check the current rule there; upgrading the account to *Pay As You Go* keeps free resources free and avoids it, but then anything beyond the free limits is billed.
- Oracle's terms forbid content that infringes copyright. HomeFlix shows films from unlicensed streaming sites, so the account can be closed without warning. Keep the sign-in required and copy the database home from time to time:
  `scp -i $key "${server}:~/homeflix/homeflix.db" homeflix-server-backup.db`

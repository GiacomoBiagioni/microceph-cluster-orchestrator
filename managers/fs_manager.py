from multipass_manager import MultipassManager
from getpass import getpass
from configs import FSConfig
import logging
import time
import re
import shlex

class FSManager:
    """Gestisce la configurazione del filesystem CephFS"""
    
    def __init__(self, multipass: MultipassManager, primary_node_name: str, nodes: list):
        # Internal variables
        self._has_typed_password = False

        self.multipass = multipass
        self.logger = logging.getLogger(__name__)
        self.PRIMARY_NODE_NAME = primary_node_name
        self.nodes = nodes
        
        self.samba_cfg = FSConfig()
        
        self._INTERNAL_FS_NAME = "cephfs"
        self._INTERNAL_POOL_META = "cephfs_meta"
        self._INTERNAL_POOL_DATA = "cephfs_data"

    def setup(self):
        """Configura il filesystem CephFS"""
            
        self.logger.info(f"Configurando il filesystem CephFS con nome {self._INTERNAL_FS_NAME}...")

        try:
            pools_exists = self._check_pool_exists(self.PRIMARY_NODE_NAME)

            if not pools_exists:
                self.logger.info("Creando pool per CephFS...")

                # Pool per metadata (più piccolo, più repliche)
                success = self.multipass.execute_command([
                    "multipass", "exec", self.PRIMARY_NODE_NAME,
                    "--", "sudo", "ceph", "osd", "pool", "create", self._INTERNAL_POOL_META, "64"
                ])
                if not success:
                    self.logger.error(f"Errore nella creazione del pool {self._INTERNAL_POOL_META}")
                    return False

                # Pool per data (più grande)
                success = self.multipass.execute_command([
                    "multipass", "exec", self.PRIMARY_NODE_NAME,
                    "--", "sudo", "ceph", "osd", "pool", "create", self._INTERNAL_POOL_DATA, "128"
                ])
                if not success:
                    self.logger.error(f"Errore nella creazione del pool {self._INTERNAL_POOL_DATA}")
                    return False
            else:
                self.logger.info("Pool CephFS già esistenti, salto la creazione")

            # 2. Verifica se il filesystem CephFS esiste già
            if not self._check_filesystem_exists(self.PRIMARY_NODE_NAME):
                # Crea il filesystem CephFS
                self.logger.info(f"Creando filesystem {self._INTERNAL_FS_NAME}...")
                success = self.multipass.execute_command([
                    "multipass", "exec", self.PRIMARY_NODE_NAME,
                    "--", "sudo", "ceph", "fs", "new", self._INTERNAL_FS_NAME, self._INTERNAL_POOL_META, self._INTERNAL_POOL_DATA
                ])
                if not success:
                    self.logger.error(f"Errore nella creazione del filesystem {self._INTERNAL_FS_NAME}")
                    return False
            else:
                self.logger.info(f"Filesystem {self._INTERNAL_FS_NAME} già esistente, salto la creazione")

            # 3. Monta il filesystem su tutti i nodi
            for node in self.nodes:
                node_name = node["name"]
                if not self._mount_cephfs_on_node(node_name):
                    self.logger.warning(f"Errore nel montaggio di CephFS su {node_name}")
                    # Non ritornare False qui, continua con gli altri nodi
        
            # 4. Configura Samba sul nodo primario (opzionale)
            self._setup_samba_share(self.PRIMARY_NODE_NAME)

            self.logger.info("Filesystem CephFS configurato con successo!")
            return True
        
        except Exception as e:
            self.logger.error(f"Errore durante la configurazione del filesystem: {e}")
            return False
         
    def _wait_for_mds_active(self, node_name: str, timeout: int = 300) -> bool:
        """Aspetta che l'MDS sia in stato active per il filesystem specificato"""
        self.logger.info(f"Attendendo che l'MDS sia attivo per {self._INTERNAL_FS_NAME}...")
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            # Verifica lo stato dell'MDS
            output = self.multipass.execute_cmd_with_output(node_name, [
                "sudo", "ceph", "mds", "stat"
            ], silent=True)
            
            if output:
                self.logger.debug(f"Stato MDS: {output}")
                # Cerca pattern come "cephfs:1 {0=ceph-node-2=up:active}"
                if re.search(rf"{self._INTERNAL_FS_NAME}:\d+.*up:active", output):
                    self.logger.info("MDS è ora attivo!")
                    return True
                    
                # Se è ancora in creating, attendiamo
                if "up:creating" in output:
                    self.logger.info("MDS ancora in fase di creazione, attendo...")
                    time.sleep(10)
                    continue
                    
                # Altri stati
                self.logger.info(f"MDS in stato: {output.strip()}, attendo...")
                
            time.sleep(5)
        
        self.logger.error(f"Timeout: MDS non è diventato attivo entro {timeout} secondi")
        return False

    def _check_pool_exists(self, node_name: str) -> bool:
        """Verifica se i pool CephFS esistono già"""
        output = self.multipass.execute_cmd_with_output(node_name, [
            "sudo", "ceph", "osd", "pool", "ls"
        ])

        if not output:
            return False

        pools = output.strip().split('\n')
        return self._INTERNAL_POOL_META in pools and self._INTERNAL_POOL_DATA in pools

    def _check_filesystem_exists(self, node_name: str) -> bool:
        """Verifica se il filesystem CephFS esiste già"""
        output = self.multipass.execute_cmd_with_output(node_name, [
            "sudo", "ceph", "fs", "ls"
        ])

        if not output:
            return False

        return self._INTERNAL_FS_NAME in output
    
    def _mount_cephfs_on_node(self, node_name: str) -> bool:
        """Monta CephFS su un nodo specifico"""
        # Verifica se è già montato
        check_mount = self.multipass.execute_cmd_with_output(node_name, [
            "bash", "-c", f"mount | grep {self.samba_cfg.mount_point}"
        ], silent=True)

        if check_mount and self.samba_cfg.mount_point in check_mount:
            self.logger.info(f"CephFS già montato su {node_name}")
            return True

        self.logger.info(f"Montando CephFS su {node_name} in {self.samba_cfg.mount_point}")

        # Crea la directory di mount
        success = self.multipass.execute_command([
            "multipass", "exec", node_name,
            "--", "sudo", "mkdir", "-p", self.samba_cfg.mount_point
        ])
        if not success:
            self.logger.error(f"Errore nella creazione della directory {self.samba_cfg.mount_point} su {node_name}")
            return False

        # Aspetta che l'MDS sia attivo prima di montare
        if not self._wait_for_mds_active(node_name):
            self.logger.error("MDS non è attivo, impossibile montare CephFS")
            return False

        keyring_path = self.PRIMARY_NODE_NAME == node_name and "/var/snap/microceph/current/conf/ceph.client.admin.keyring" or "/var/snap/microceph/current/conf/ceph.keyring"

        # Monta usando ceph-fuse
        success = self.multipass.execute_command([
            "multipass", "exec", node_name,
            "--", "sudo", "ceph-fuse", 
            "-n", "client.admin",
            "--keyring", keyring_path,
            "--conf", "/var/snap/microceph/current/conf/ceph.conf",
            self.samba_cfg.mount_point
        ])

        if not success:
            self.logger.error(f"Errore nel montaggio di CephFS su {node_name}")
            return False

        self.logger.info(f"CephFS montato con successo su {node_name}")
        return True

    def _setup_samba_share(self, node_name: str) -> bool:
        """Configura la condivisione Samba per CephFS (opzionale, richiede input utente)"""
        self.logger.info(f"Configurando condivisione Samba su {node_name}")

        try:
            # Verifica se la sezione [<share_name>] è già presente in smb.conf
            config_exists = self.multipass.execute_command([
                "multipass", "exec", node_name,
                "--", "grep", "-Fxq", f"[{self.samba_cfg.share_name}]", "/etc/samba/smb.conf"
            ])

            if config_exists:
                self.logger.info(f"Configurazione Samba [{self.samba_cfg.share_name}] già presente, salto aggiornamento e riavvio")
            else:
                # Input interattivo con valori di default
                user_input = input(f"Inserisci il nome utente Samba [{self.samba_cfg.samba_username}]: ").strip()
                self.samba_cfg.samba_username = user_input or self.samba_cfg.samba_username
                password_input = getpass(f"Inserisci la password Samba [{self.samba_cfg.samba_password}]: ").strip()
                self.samba_cfg.samba_password = password_input or self.samba_cfg.samba_password
                share_name_input = input(f"Inserisci il nome della condivisione Samba (//ip/[{self.samba_cfg.share_name}]): ").strip()
                self.samba_cfg.share_name = share_name_input or self.samba_cfg.share_name

                self.logger.info(f"Creando/aggiornando utente {self.samba_cfg.samba_username}...")
                self._has_typed_password = True

                # Verifica se l'utente esiste già (utente di sistema)
                user_exists = self.multipass.execute_command([
                    "multipass", "exec", node_name,
                    "--", "id", "-u", self.samba_cfg.samba_username
                ])

                if user_exists:
                    self.logger.info(f"Utente {self.samba_cfg.samba_username} già esistente")
                else:
                    # Aggiungi l'utente di sistema
                    success = self.multipass.execute_command([
                        "multipass", "exec", node_name,
                        "--", "sudo", "adduser", "--disabled-password", "--gecos", "", self.samba_cfg.samba_username
                    ])
                    if not success:
                        self.logger.error(f"Errore nella creazione dell'utente {self.samba_cfg.samba_username}")
                        return False

                # Imposta/aggiorna la password Samba
                smb_cmd = (
                    f"PASS={shlex.quote(self.samba_cfg.samba_password)}; "
                    f"printf '%s\\n%s\\n' \"$PASS\" \"$PASS\" | "
                    f"sudo smbpasswd -s {'-a ' if not user_exists else ''}{shlex.quote(self.samba_cfg.samba_username)}"
                )
                success = self.multipass.execute_command([
                    "multipass", "exec", node_name,
                    "--", "bash", "-c", smb_cmd
                ])
                if not success:
                    self.logger.error("Errore nell'impostazione della password Samba")
                    return False

                # Cambia proprietario della directory
                success = self.multipass.execute_command([
                    "multipass", "exec", node_name,
                    "--", "sudo", "chown", "-R", f"{self.samba_cfg.samba_username}:{self.samba_cfg.samba_username}", self.samba_cfg.mount_point
                ])
                if not success:
                    self.logger.error(f"Errore nel cambio proprietario di {self.samba_cfg.mount_point}")
                    return False

                # Configura Samba - aggiungi la sezione alla configurazione
                samba_config = (
                    f"[{self.samba_cfg.share_name}]\n"
                    f"path = {self.samba_cfg.mount_point}\n"
                    "browseable = yes\n"
                    "read only = no\n"
                    f"valid users = {self.samba_cfg.samba_username}\n"
                    "create mask = 0755\n"
                    "directory mask = 0755\n"
                )

                # Scrivi la configurazione in modo sicuro (gestendo eventuali apici)
                safe_config = samba_config.replace("'", "'\"'\"'")
                success = self.multipass.execute_command([
                    "multipass", "exec", node_name,
                    "--", "bash", "-c",
                    f"echo '{safe_config}' | sudo tee -a /etc/samba/smb.conf >/dev/null"
                ])
                if not success:
                    self.logger.error("Errore nella configurazione di Samba")
                    return False

                # Riavvia il servizio Samba
                success = self.multipass.execute_command([
                    "multipass", "exec", node_name,
                    "--", "sudo", "systemctl", "restart", "smbd"
                ])
                if not success:
                    self.logger.error("Errore nel riavvio del servizio Samba")
                    return False
                
            return True

        except Exception as e:
            self.logger.error(f"Errore nella configurazione Samba: {e}")
            return False

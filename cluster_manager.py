from configs import NodesCreationConfig
from multipass_manager import MultipassManager
from managers.fs_manager import FSManager
import logging
import re

class ClusterManager:
    PRIMARY_NODE_NAME = "ceph-node-1"
    CLIENT_VM_NAME = "ceph-client"

    def __init__(self, is_debug = False):
        self.nodes = []
        self.multipass = MultipassManager(is_debug)
        self.logger = logging.getLogger(__name__)
        self.fs_manager = FSManager(multipass=self.multipass, primary_node_name=self.PRIMARY_NODE_NAME, nodes=self.nodes)

        # Configura il logging se non è già configurato
        if not self.logger.handlers:
            logging.basicConfig(
                level=logging.INFO,
                format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )

    def add_node(self, node):
        self.nodes.append(node)

    def remove_node(self, node):
        if node in self.nodes:
            self.nodes.remove(node)

    def list_nodes(self):
        return self.nodes

    def get_cluster_info(self):
        """Ottiene informazioni dettagliate sul cluster"""
        cluster_info = {
            "nodes": self.list_nodes(),
            "total_nodes": len(self.nodes)
        }
        
        # Aggiungi informazioni live da Multipass se disponibile
        if self.multipass.is_multipass_available():
            live_instances = self.multipass.list_instances()
            cluster_info["live_instances"] = live_instances
            
            # Aggiorna lo stato dei nodi
            for node in self.nodes:
                node_name = node.get("name")
                for instance in live_instances:
                    if instance.get("name") == node_name:
                        node["multipass_state"] = instance.get("state", "unknown")
                        node["ipv4"] = instance.get("ipv4", [])
                        break
        
        return cluster_info
    
    def get_setup_parameters(self):
        """Raccoglie i parametri per il setup del cluster dall'utente"""
        print("\n=== Configurazione Cluster Ceph ===")
        print("Inserisci i parametri per il setup (premi Enter per usare il valore di default):\n")
        
        # Numero di nodi (default: 2)
        while True:
            node_count_input = input("Numero di nodi [2]: ").strip()
            if not node_count_input:
                node_count = 2
                break
            try:
                node_count = int(node_count_input)
                if node_count < 1:
                    print("Il numero di nodi deve essere almeno 1")
                    continue
                break
            except ValueError:
                print("Inserisci un numero valido")
        
        # Base name (default: ceph-node)
        base_name = input("Nome base per i nodi [ceph-node]: ").strip()
        if not base_name:
            base_name = "ceph-node"
        
        # CPU (default: 2)
        while True:
            cpu_input = input("Numero di CPU per nodo [2]: ").strip()
            if not cpu_input:
                cpus = 2
                break
            try:
                cpus = int(cpu_input)
                if cpus < 1:
                    print("Il numero di CPU deve essere almeno 1")
                    continue
                break
            except ValueError:
                print("Inserisci un numero valido")
        
        # RAM (default: 2G)
        # RAM (default: 2G)
        while True:
            ram_input = input("Quantità di RAM per nodo [2G]: ").strip()
            if not ram_input:
                memory = "2G"
                break
            
            # Verifica formato: numero positivo, opzionale K/M/G
            if re.fullmatch(r"\d+([KMG])?", ram_input, re.IGNORECASE):
                memory = ram_input.upper()
                break
            else:
                print("Inserisci una quantità valida (es: 2048, 2G, 512M, 4096K)")

        # Dimensione disco (default: 10G)
        while True:
            disk_input = input("Dimensione disco per nodo [10G]: ").strip()
            if not disk_input:
                disk = "10G"
                break
            
            if re.fullmatch(r"\d+([KMG])?", disk_input, re.IGNORECASE):
                disk = disk_input.upper()
                break
            else:
                print("Inserisci una dimensione valida (es: 10240, 10G, 512M, 4096K)")
        
        # Sistema operativo (default: 22.04)
        image_input = input("Sistema operativo [22.04 (Ubuntu)]: ").strip()
        if not image_input:
            image = "22.04"
        else:
            image = image_input
        
        # Mostra riepilogo
        print(f"\n=== Riepilogo Configurazione ===")
        print(f"Numero nodi: {node_count}")
        print(f"Nome base: {base_name}")
        print(f"CPU per nodo: {cpus}")
        print(f"RAM per nodo: {memory}")
        print(f"Disco per nodo: {disk}")
        print(f"Sistema operativo: {image}")
        
        confirm = input("\nConfermi la configurazione? [s/N]: ").strip().lower()
        if confirm not in ['s', 'si', 'y', 'yes']:
            print("Configurazione annullata.")
            return None
        
        return NodesCreationConfig(
            base_name=base_name,
            cpus=cpus,
            memory=memory,
            disk=disk,
            image=image,
            node_count=node_count
        )
    
    def create_default_config(self):
        """Crea una configurazione con valori di default"""
        return NodesCreationConfig(
            base_name="ceph-node",
            cpus=2,
            memory="2G",
            disk="10G",
            image="22.04",
            node_count=2
        )
    
    def setup_vms(self, config=None):
        """Crea le VM del cluster usando Multipass"""
        # Verifica che Multipass sia disponibile
        if not self.multipass.is_multipass_available():
            self.logger.error("Multipass non è disponibile nel sistema. Assicurati che sia installato e nel PATH.")
            return False

        # Se non è stata fornita una configurazione, chiedila all'utente
        if config is None:
            config = self.get_setup_parameters()
            if config is None:
                self.logger.info("Setup annullato dall'utente.")
                return False

        self.logger.info(f"Iniziando la creazione di {config.node_count} VM per il cluster Ceph...")
        
        success_count = 0
        for i in range(config.node_count):
            node_name = f"{config.base_name}-{i+1}"
            
            # Crea la VM con Multipass
            if self.multipass.create_instance(
                name=node_name,
                cpus=config.cpus,
                memory=config.memory,
                disk=config.disk,
                image=config.image,
                is_primary=(i == 0)
            ):
                # Se la creazione è riuscita, aggiungi il nodo alla lista
                node_info = {
                    "name": node_name,
                    "cpus": config.cpus,
                    "memory": config.memory,
                    "disk": config.disk,
                    "image": config.image,
                    "status": "created"
                }
                self.add_node(node_info)

                success_count += 1
                self.logger.info(f"VM {node_name} creata e aggiunta al cluster ({i+1}/{config.node_count})")
            else:
                self.logger.error(f"Fallimento nella creazione della VM {node_name}")
        
        if success_count == config.node_count:
            self.logger.info(f"Tutte le {config.node_count} VM sono state create con successo!")
            return True
        else:
            self.logger.warning(f"Solo {success_count}/{config.node_count} VM sono state create con successo")
            return False

    def create_cluster(self):
        """Crea il cluster Ceph"""
        if not self.nodes:
            self.logger.error("Nessun nodo disponibile per creare il cluster")
            return False
        
        # Controlla se tutti i nodi sono già presenti nel cluster
        cluster_list_output = self.multipass.execute_cmd_with_output(self.PRIMARY_NODE_NAME, [
            "sudo", "microceph", "cluster", "list"
        ])

        already_joined = set()
        if cluster_list_output and isinstance(cluster_list_output, str):
            # Estrai i nomi dei nodi già nel cluster dalla tabella
            for line in cluster_list_output.splitlines():
                if line.startswith("|"):
                    parts = [p.strip() for p in line.split("|")[1:-1]]
                    if parts and parts[0].startswith("ceph-node"):
                        already_joined.add(parts[0])

        # Skippa la configurazione se tutti i nodi sono già nel cluster
        expected_nodes = {node["name"] for node in self.nodes}
        if expected_nodes.issubset(already_joined):
            self.logger.info("Tutti i nodi sono già presenti nel cluster, nessuna configurazione necessaria.")
            return True

        # Esegui i comandi necessari per configurare il cluster
        # Questo è un placeholder, dovresti implementare la logica di configurazione del cluster
        self.logger.info("Configurando il cluster Ceph...")
        
        # Simula la configurazione del cluster
        for node in self.nodes:
            if node["name"] == self.PRIMARY_NODE_NAME:
                continue

            token = self.multipass.get_token(self.PRIMARY_NODE_NAME, node["name"])
            if token:
                self.multipass.execute_command([
                    "multipass", "exec", node["name"],
                    "--", "sudo", "microceph", "cluster", "join", token
                ])
            else:
                self.logger.error(f"Impossibile ottenere il token per {node['name']}")
                return False

        
        self.logger.info("Cluster Ceph creato con successo!")
        return True
    
    def setup_osds(self):
        """Configura gli OSD nel cluster"""
        if not self.nodes:
            self.logger.error("Nessun nodo disponibile per configurare gli OSD")
            return False
        
        self.logger.info("Configurando gli OSD per il cluster Ceph...")
        
        # Esegui i comandi necessari per configurare gli OSD
        for node in self.nodes:
            node_name = node["name"]

            # Verifica se un OSD è già presente per questo nodo (evita duplicati)
            if self._node_has_osd(node_name):
                self.logger.info(f"OSD già presente su {node_name}, salto l'aggiunta del disco")
                continue

            # Aggiungi il disco (loopback) a microceph per creare un OSD su questo nodo
            success = self.multipass.execute_command([
                "multipass", "exec", node_name,
                "--", "sudo", "microceph", "disk", "add", "loop,4G,1"
            ])

            if not success:
                self.logger.error(f"Errore nell'aggiunta del disk a microceph su {node_name}")
                return False

            # Verifica post-condizione: l'OSD dovrebbe ora essere presente
            if not self._node_has_osd(node_name):
                self.logger.warning(f"Dopo l'aggiunta il nodo {node_name} non risulta avere OSD; controllare manualmente")
            else:
                self.logger.info(f"OSD creato su {node_name}")
        
        self.logger.info("OSD configurati con successo!")
        return True
        
    def _node_has_osd(self, node_name: str) -> bool:
        """Rileva se esiste già almeno un OSD associato al nodo indicato.

        Implementazione: esegue `microceph disk list` (vista cluster) sul nodo
        e analizza la tabella testuale cercando una riga con LOCATION uguale a `node_name`.
        """
        output = self.multipass.execute_cmd_with_output(node_name, [
            "sudo", "microceph", "disk", "list"
        ])

        if not output or not isinstance(output, str):
            # Se non possiamo determinare, assumiamo che non ci sia per evitare falsi duplicati
            self.logger.debug(f"Impossibile leggere la lista dischi da {node_name}: output vuoto o non valido")
            return False

        found = False
        for line in output.splitlines():
            line = line.rstrip()
            # Linee utili della tabella iniziano con '|'
            if not line.startswith("|"):
                continue
            # Estrarre le colonne tra i separatori '|'
            parts = [p.strip() for p in line.split("|")[1:-1]]
            if len(parts) < 3:
                continue
            osd_col, location_col, _path_col = parts[0], parts[1], parts[2]
            # Salta riga di header dove OSD == 'OSD'
            if osd_col.lower() == "osd":
                continue
            # Se la LOCATION corrisponde al nodo, abbiamo trovato un OSD per questo nodo
            if location_col == node_name:
                found = True
                break

        return found
   
    def create_client_vm(self):
        """Crea una VM client per accedere al filesystem CephFS"""
        self.logger.info(f"Creando VM client {self.CLIENT_VM_NAME}...")

        self.multipass.create_instance(
            name=self.CLIENT_VM_NAME,
            cpus=1,
            memory="1G",
            disk="5G",
            image="22.04",
            is_primary=False,
            is_client=True
        )

        config_exists = self.multipass.execute_command([
            "multipass", "exec", self.CLIENT_VM_NAME, "--",
            "grep", "-Fxq", f"[{self.fs_manager.samba_cfg.share_name}]", "/etc/samba/smb.conf"
        ])

        if config_exists:
            self.logger.info(f"Configurazione Samba [{self.fs_manager.samba_cfg.share_name}] già presente, salto aggiornamento e riavvio")
        else:
            """Configura Samba sulla VM client per condividere CephFS via rete"""
            self.logger.info("Configurando Samba sulla VM client...")

            samba_commands = [
                # Crea un utente Samba
                ["sudo", "useradd", "-m", self.fs_manager.samba_cfg.samba_username],
                ["sudo", "chown", "-R", f"{self.fs_manager.samba_cfg.samba_username}:{self.fs_manager.samba_cfg.samba_username}", self.fs_manager.samba_cfg.mount_point],
                ["sudo", "chmod", "-R", "755", self.fs_manager.samba_cfg.mount_point],
            ]

            for cmd in samba_commands:
                self.multipass.execute_cmd_with_output(self.CLIENT_VM_NAME, cmd)

            # Configura Samba
            samba_config = f"""
    [{self.fs_manager.samba_cfg.share_name}]
    path = {self.fs_manager.samba_cfg.mount_point}
    browseable = yes
    read only = no
    valid users = {self.fs_manager.samba_cfg.samba_username}
    create mask = 0755
    directory mask = 0755
    public = yes
    guest ok = yes
    """

            # Aggiungi la configurazione Samba
            config_cmd = f"echo '{samba_config}' | sudo tee -a /etc/samba/smb.conf > /dev/null"
            self.multipass.execute_cmd_with_output(self.CLIENT_VM_NAME, [
                "bash", "-c", config_cmd
            ])

            # Riavvia Samba
            self.multipass.execute_command([
                "multipass", "exec", self.CLIENT_VM_NAME, "--", "sudo", "systemctl", "restart", "smbd"
            ])

            # Ottieni l'IP della VM client
            client_ip = self.multipass.get_instance_ip(self.PRIMARY_NODE_NAME)

            # Monta la condivisione solo se non è già montata
            already_mounted = self.multipass.execute_command([
                "multipass", "exec", self.CLIENT_VM_NAME, "--",
                "findmnt", "-rn", "-t", "cifs",
                "-S", f"//{client_ip}/{self.fs_manager.samba_cfg.share_name}",
                "-T", self.fs_manager.samba_cfg.mount_point
            ])

            if already_mounted:
                self.logger.info(f"Condivisione già montata su {self.fs_manager.samba_cfg.mount_point}, salto il mount")
            else:
                self.multipass.execute_cmd_with_output(self.CLIENT_VM_NAME, [
                    "sudo", "mount", "-t", "cifs",
                    f"//{client_ip}/{self.fs_manager.samba_cfg.share_name}",
                    self.fs_manager.samba_cfg.mount_point,
                    "-o", f"username={self.fs_manager.samba_cfg.samba_username},password={self.fs_manager.samba_cfg.samba_password},rw"
                ])

        return True
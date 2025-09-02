import subprocess
import json
import logging
from typing import List, Dict, Optional
import base64

class MultipassManager:
    """Gestore per operazioni Multipass"""
    
    def __init__(self, is_debug: bool = False):
        self.logger = logging.getLogger(__name__)
        self._is_debug = is_debug
    
    def is_multipass_available(self) -> bool:
        """Verifica se Multipass è disponibile nel sistema"""
        try:
            result = subprocess.run(['multipass', 'version'], 
                                  capture_output=True, text=True, timeout=10)
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
    
    def list_instances(self) -> List[Dict]:
        """Lista tutte le istanze Multipass"""
        try:
            result = subprocess.run(['multipass', 'list', '--format', 'json'],
                                  capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                data = json.loads(result.stdout)
                return data.get('list', [])
            else:
                self.logger.error(f"Errore nel listare le istanze: {result.stderr}")
                return []
        except Exception as e:
            self.logger.error(f"Errore nel listare le istanze: {e}")
            return []
    
    def instance_exists(self, name: str) -> bool:
        """Verifica se un'istanza esiste"""
        instances = self.list_instances()
        return any(instance['name'] == name for instance in instances)
    
    def get_instance_ip(self, name: str) -> Optional[str]:
        """Ottiene l'IP di un'istanza Multipass"""
        instances = self.list_instances()
        for instance in instances:
            if instance['name'] == name:
                ipv4_list = instance.get('ipv4', [])
                if ipv4_list:
                    return ipv4_list[0]  # Restituisce il primo IP
        return None

    def get_token(self, main_vm_name: str, target_vm_name: str) -> Optional[str]:
        """Ottiene il token di un'istanza Multipass"""
        try:
            result = subprocess.run(["multipass", "exec", main_vm_name, "--", "sudo", "microceph", "cluster", "add", target_vm_name],
                                  capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                # Supponiamo che il token sia nell'output
                output = result.stdout.strip()
                if output:
                    return output
                else:
                    self.logger.error(f"Nessun token trovato per {target_vm_name}")
                    return None
            else:
                self.logger.error(f"Errore nel recuperare il token per {target_vm_name}: {result.stderr}")
                return None
            
        except Exception as e:
            self.logger.error(f"Errore nel recuperare il token per {main_vm_name}: {e}")
            return None

    def execute_command(self, command: List[str], silent: bool = False) -> bool:
        """Esegue un comando Multipass"""
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=240)
            if result.returncode == 0:
                if not silent and self._is_debug:
                    self.logger.info(f"Comando eseguito con successo: {' '.join(command)}")
                return True
            else:
                self.logger.error(f"Errore nell'esecuzione del comando {' '.join(command)}: {result.stderr}")
                return False
        except Exception as e:
            self.logger.error(f"Errore nell'esecuzione del comando {' '.join(command)}: {e}")
            return False

    def execute_cmd_with_output(self, instance_name: str, cmd: List[str], silent: bool = False) -> Optional[str]:
        """Esegue un comando all'interno di un'istanza Multipass"""
        full_command = ["multipass", "exec", instance_name, "--"] + cmd

        try:
            result = subprocess.run(full_command, capture_output=True, text=True, timeout=240)
            if result.returncode == 0:
                if not silent and self._is_debug:
                    self.logger.info(f"Comando eseguito con successo: {' '.join(full_command)}")
                return result.stdout
            else:
                self.logger.error(f"Errore nell'esecuzione del comando {' '.join(full_command)}: {result.stderr}")
                return None
        except Exception as e:
            self.logger.error(f"Errore nell'esecuzione del comando {' '.join(full_command)}: {e}")
            return None

    def create_instance(self, name: str, cpus: int = 2, memory: str = "2G", 
                       disk: str = "10G", image: str = "22.04", is_primary: bool = False, is_client: bool = False) -> bool:
        """Crea una nuova istanza Multipass"""
        if self.instance_exists(name):
            self.logger.warning(f"L'istanza {name} esiste già")
            return True
        
        try:
            if is_client:
                cloud_init_file = 'cloud-init/cloud-init-client.yaml'
            elif is_primary:
                cloud_init_file = 'cloud-init/cloud-init-master.yaml'
            else:
                cloud_init_file = 'cloud-init/cloud-init-slave.yaml'
                
            cmd = [
                'multipass', 'launch',
                '--name', name,
                '--cpus', str(cpus),
                '--memory', memory,
                '--disk', disk,
                image,
                '--cloud-init', cloud_init_file
            ]
            
            self.logger.info(f"Creando istanza {name} con {cpus} CPU, {memory} RAM, {disk} disk...")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            
            if result.returncode != 0:
                self.logger.error(f"Errore nella creazione dell'istanza {name}: {result.stderr}")
                return False

            self.logger.info(f"Istanza {name} creata con successo")

            result = self.set_netplan_static_ip(name)
            if not result:
                self.logger.error(f"Errore nella configurazione dell'IP statico per l'istanza {name}")
                return False

            return True
                
        except subprocess.TimeoutExpired:
            self.logger.error(f"Timeout nella creazione dell'istanza {name}")
            return False
        except Exception as e:
            self.logger.error(f"Errore nella creazione dell'istanza {name}: {e}")
            return False
        
    def set_netplan_static_ip(self, node_name: str) -> bool:
        """Configura un IP statico tramite netplan su un'istanza Multipass"""
        
        try:
            # Rileva interfaccia, IP/CIDR e gateway dalla VM
            iface = self.execute_cmd_with_output(node_name,
                ["bash", "-lc", "ip route get 1.1.1.1 | awk '{print $5}' | head -n1"],
                silent=True,
            )
            if not iface:
                self.logger.error("Impossibile rilevare l'interfaccia di rete")
                return False
            
            iface = iface.strip()

            ip_cidr = self.execute_cmd_with_output(
                node_name,
                ["bash", "-lc", f"ip -o -4 addr show dev {iface} | awk '{{print $4}}' | head -n1"],
                silent=True,
            )
            if not ip_cidr:
                self.logger.error("Impossibile rilevare l'IP della VM")
                return False
            
            ip_cidr = ip_cidr.strip()

            gateway = self.execute_cmd_with_output(
                node_name,
                ["bash", "-lc", "ip route | awk '/^default/ {print $3; exit}'"],
                silent=True,
            )
            if not gateway:
                self.logger.error("Impossibile rilevare il gateway della VM")
                return False
            
            gateway = gateway.strip()

            # Contenuto netplan
            yaml_content = f"""
            network:
              version: 2
              ethernets:
                {iface}:
                  dhcp4: false
                  addresses:
                    - {ip_cidr}
                  routes:
                    - to: 0.0.0.0/0
                      via: {gateway}
                  nameservers:
                    addresses:
                      - 8.8.8.8
                      - 8.8.4.4
    """

            # Backup e scrittura file
            self.execute_cmd_with_output(
                node_name,
                ["bash", "-lc", "sudo cp -f /etc/netplan/50-cloud-init.yaml /etc/netplan/50-cloud-init.yaml.bak 2>/dev/null || true"],
                silent=True,
            )

            b64 = base64.b64encode(yaml_content.encode("utf-8")).decode("ascii")
            write_res = self.execute_cmd_with_output(
                node_name,
                ["bash", "-lc", f"echo '{b64}' | base64 -d | sudo tee /etc/netplan/50-cloud-init.yaml >/dev/null"],
             silent=True,
            )
            if write_res is None:
                self.logger.error("Errore nella scrittura del file netplan")
                return False

            # Applica netplan
            apply_res = self.execute_cmd_with_output(
                node_name,
                ["bash", "-lc", "sudo netplan apply >/dev/null 2>&1 || echo FAIL"],
                silent=True,
            )
            if apply_res and "FAIL" in apply_res:
                self.logger.error("Errore nell'applicazione di netplan")
                return False

            return True

        except Exception as e:
            self.logger.error(f"Errore nella configurazione IP statica: {e}")
            return False
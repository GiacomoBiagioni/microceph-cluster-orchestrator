import subprocess
import platform
import sys
import logging

logger = logging.getLogger(__name__)

def check_hypervisor():
    """
    Controlla se un hypervisor è disponibile e attivo sul sistema.
    
    Returns:
        tuple: (bool, str) - (is_available, hypervisor_info)
    """
    system = platform.system().lower()
    
    try:
        if system == "windows":
            return _check_windows_hyperv()
        elif system == "linux":
            return _check_linux_hypervisors()
        else:
            return False, f"Sistema operativo '{system}' non supportato"
    except Exception as e:
        logger.error(f"Errore durante il controllo dell'hypervisor: {e}")
        return False, f"Errore durante il controllo: {str(e)}"

def _check_windows_hyperv():
    """Controlla se Hyper-V è disponibile e abilitato su Windows"""
    try:
        # Prima prova con Get-WindowsOptionalFeature (richiede privilegi elevati)
        result = subprocess.run(
            ["powershell", "-Command", "Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All"],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            output = result.stdout.lower()
            if "state" in output and "enabled" in output:
                # Controlla anche se il servizio Hyper-V è in esecuzione
                service_result = subprocess.run(
                    ["powershell", "-Command", "Get-Service -Name vmms -ErrorAction SilentlyContinue"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if service_result.returncode == 0 and "running" in service_result.stdout.lower():
                    return True, "Hyper-V è installato, abilitato e in esecuzione"
                else:
                    return False, "Hyper-V è installato ma il servizio non è in esecuzione"
        
        # Se il comando fallisce (probabilmente per mancanza di privilegi), prova metodi alternativi
        if "privilegi elevati" in result.stderr.lower() or "elevated" in result.stderr.lower():
            return _check_windows_hyperv_alternative()
        
        # Se non è abilitato, controlla hypervisor alternativi
        return _check_windows_alternative_hypervisors()
            
    except subprocess.TimeoutExpired:
        return False, "Timeout durante il controllo di Hyper-V"
    except Exception as e:
        logger.error(f"Errore nel controllo di Hyper-V: {e}")
        return _check_windows_hyperv_alternative()

def _check_windows_hyperv_alternative():
    """Metodo alternativo per controllare Hyper-V senza privilegi elevati"""
    try:
        # Controlla se il servizio Hyper-V è presente e in esecuzione
        result = subprocess.run(
            ["powershell", "-Command", "Get-Service -Name vmms -ErrorAction SilentlyContinue | Select-Object Status"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0 and result.stdout.strip():
            if "running" in result.stdout.lower():
                return True, "Hyper-V sembra essere attivo (servizio vmms in esecuzione)"
            else:
                return False, "Hyper-V è installato ma non attivo"
        
        # Controlla se il processo Hyper-V è in esecuzione
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq vmms.exe"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0 and "vmms.exe" in result.stdout:
            return True, "Hyper-V sembra essere attivo (processo vmms.exe trovato)"
        
        # Se Hyper-V non è disponibile, controlla alternative
        return _check_windows_alternative_hypervisors()
        
    except Exception as e:
        logger.error(f"Errore nel controllo alternativo di Hyper-V: {e}")
        return _check_windows_alternative_hypervisors()

def _check_windows_alternative_hypervisors():
    """Controlla hypervisor alternativi su Windows"""
    # Controlla VirtualBox
    try:
        result = subprocess.run(
            ["vboxmanage", "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            return True, f"VirtualBox disponibile (versione: {version})"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    
    # Controlla VMware
    try:
        result = subprocess.run(
            ["vmrun", "-T", "ws", "list"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            return True, "VMware Workstation disponibile"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    
    return False, "Nessun hypervisor supportato trovato. Installare Hyper-V, VirtualBox o VMware"

def _check_linux_hypervisors():
    """Controlla hypervisor disponibili su Linux"""
    hypervisors_found = []
    
    # Controlla KVM
    try:
        # Verifica se il modulo KVM è caricato
        result = subprocess.run(
            ["lsmod"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0 and ("kvm" in result.stdout.lower()):
            hypervisors_found.append("KVM")
    except Exception:
        pass
    
    # Controlla libvirt/QEMU
    try:
        result = subprocess.run(
            ["virsh", "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            print("Trovato 'libvirt/QEMU' come hypervisor. (KVM è consigliato)")
            hypervisors_found.append("libvirt/QEMU")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    
    if hypervisors_found:
        return True, f"Hypervisor disponibili: {', '.join(hypervisors_found)}"
    else:
        return False, "Nessun hypervisor supportato trovato. Installare KVM, VirtualBox, VMware o libvirt"

def print_hypervisor_status():
    """Stampa lo stato dell'hypervisor in modo user-friendly"""
    is_available, info = check_hypervisor()
    
    if is_available:
        print(f"Hypervisor disponibile: {info}")
        return True
    else:
        print(f"Problema con l'hypervisor: {info}")
        print("\n Suggerimenti:")
        
        system = platform.system().lower()
        if system == "windows":
            print("   - Per abilitare Hyper-V: Esegui come amministratore:")
            print("     Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V -All")
            print("   - Oppure installa VirtualBox: https://www.virtualbox.org/")
        elif system == "linux":
            print("   - Per installare KVM: sudo apt install qemu-kvm libvirt-daemon-system")
            print("   - Oppure installa VirtualBox: sudo apt install virtualbox")
        elif system == "darwin":
            print("   - Installa VirtualBox: https://www.virtualbox.org/")
            print("   - Oppure VMware Fusion: https://www.vmware.com/products/fusion.html")
        
        return False

if __name__ == "__main__":
    # Test della funzione
    print_hypervisor_status()

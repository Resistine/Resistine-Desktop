import Foundation
import NetworkExtension

class VPNController: NSObject {
    static let shared = VPNController()
    
    private let extensionBundleIdentifier = "com.resistine.desktop.network-extension"
    private var tunnelManager: NETunnelProviderManager?
    private var isOperationInProgress = false
    
    private override init() {
        super.init()
    }
    
    func start(config: String, completionHandler: @escaping (Bool) -> Void) {
        guard !isOperationInProgress else {
            NSLog("WARNING [Start]: Operation already in progress. Ignoring.")
            completionHandler(false)
            return
        }
        
        isOperationInProgress = true
        NSLog("--- START: Attempting to turn ON tunnel ---")
        
        loadManager { [weak self] manager in
            guard let self = self, let manager = manager else {
                self?.isOperationInProgress = false
                completionHandler(false)
                return
            }
            
            let protocolConfiguration = NETunnelProviderProtocol()
            protocolConfiguration.providerBundleIdentifier = self.extensionBundleIdentifier
            protocolConfiguration.serverAddress = "WireGuard Server"
            protocolConfiguration.providerConfiguration = ["wgQuickConfig": config]
            
            manager.protocolConfiguration = protocolConfiguration
            manager.localizedDescription = "Resistine VPN Tunnel"
            manager.isEnabled = true
            
            NSLog("STATUS [Start]: Saving preferences...")
            manager.saveToPreferences { error in
                if let error = error {
                    NSLog("ERROR [Start]: saveToPreferences failed: \(error.localizedDescription)")
                    self.isOperationInProgress = false
                    completionHandler(false)
                    return
                }
                
                NSLog("STATUS [Start]: Loading preferences back...")
                manager.loadFromPreferences { error in
                    if let error = error {
                        NSLog("ERROR [Start]: loadFromPreferences failed: \(error.localizedDescription)")
                        self.isOperationInProgress = false
                        completionHandler(false)
                        return
                    }
                    
                    do {
                        NSLog("ACTION [Start]: Starting tunnel...")
                        try (manager.connection as? NETunnelProviderSession)?.startTunnel()
                        NSLog("SUCCESS [Start]: startTunnel called.")
                        self.isOperationInProgress = false
                        completionHandler(true)
                    } catch {
                        NSLog("ERROR [Start]: startTunnel failed: \(error.localizedDescription)")
                        self.isOperationInProgress = false
                        completionHandler(false)
                    }
                }
            }
        }
    }
    
    func stop(completionHandler: @escaping (Bool) -> Void = { _ in }) {
        guard !isOperationInProgress else {
            NSLog("WARNING [Stop]: Operation already in progress. Ignoring.")
            completionHandler(false)
            return
        }
        
        isOperationInProgress = true
        NSLog("--- STOP: Attempting to turn OFF tunnel ---")
        
        loadManager { [weak self] manager in
            guard let self = self, let manager = manager else {
                self?.isOperationInProgress = false
                completionHandler(false)
                return
            }
            
            let session = manager.connection as? NETunnelProviderSession
            let status = session?.status ?? .invalid
            NSLog("STATUS [Stop]: Current status is \(status)")
            
            if status == .connected || status == .connecting || status == .reasserting {
                NSLog("ACTION [Stop]: Stopping tunnel...")
                session?.stopTunnel()
                self.isOperationInProgress = false
                completionHandler(true)
            } else {
                NSLog("STATUS [Stop]: Tunnel is not active. No action taken.")
                self.isOperationInProgress = false
                completionHandler(true)
            }
        }
    }
    
    func status(completionHandler: @escaping (NEVPNStatus) -> Void) {
        loadManager { manager in
            let status = manager?.connection.status ?? .invalid
            completionHandler(status)
        }
    }
    
    private func loadManager(completion: @escaping (NETunnelProviderManager?) -> Void) {
        NETunnelProviderManager.loadAllFromPreferences { managers, error in
            if let error = error {
                NSLog("ERROR [LoadManager]: \(error.localizedDescription)")
                completion(nil)
                return
            }
            
            let manager = managers?.first ?? NETunnelProviderManager()
            completion(manager)
        }
    }
}

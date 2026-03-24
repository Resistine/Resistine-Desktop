import Foundation
import NetworkExtension
import SystemExtensions

// MARK: - VPN Controller
class VPNController: NSObject {
    static let shared = VPNController()
    
    private let extensionBundleIdentifier = "com.resistine.desktop.network-extension"
    private var isOperationInProgress = false
    private var activationCompletion: ((Bool) -> Void)?
    
    func activate(completionHandler: @escaping (Bool) -> Void) {
        guard !isOperationInProgress else {
            completionHandler(false)
            return
        }
        
        isOperationInProgress = true
        activationCompletion = completionHandler
        
        let request = OSSystemExtensionRequest.activationRequest(forExtensionWithIdentifier: extensionBundleIdentifier, queue: .main)
        request.delegate = self
        OSSystemExtensionManager.shared.submitRequest(request)
    }
    
    func start(config: String, completionHandler: @escaping (Bool) -> Void) {
        guard !isOperationInProgress else {
            completionHandler(false)
            return
        }
        
        isOperationInProgress = true
        
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
            
            manager.saveToPreferences { error in
                if let error = error {
                    NSLog("ERROR [Start]: saveToPreferences failed: \(error.localizedDescription)")
                    self.isOperationInProgress = false
                    completionHandler(false)
                    return
                }
                
                manager.loadFromPreferences { error in
                    if let error = error {
                        NSLog("ERROR [Start]: loadFromPreferences failed: \(error.localizedDescription)")
                        self.isOperationInProgress = false
                        completionHandler(false)
                        return
                    }
                    
                    do {
                        try (manager.connection as? NETunnelProviderSession)?.startTunnel()
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
    
    func stop(completionHandler: @escaping (Bool) -> Void) {
        guard !isOperationInProgress else {
            completionHandler(false)
            return
        }
        
        isOperationInProgress = true
        
        loadManager { [weak self] manager in
            guard let self = self, let manager = manager else {
                self?.isOperationInProgress = false
                completionHandler(false)
                return
            }
            
            let session = manager.connection as? NETunnelProviderSession
            let status = session?.status ?? .invalid
            
            if status == .connected || status == .connecting || status == .reasserting {
                session?.stopTunnel()
                self.isOperationInProgress = false
                completionHandler(true)
            } else {
                self.isOperationInProgress = false
                completionHandler(true)
            }
        }
    }
    
    func status(completionHandler: @escaping (NEVPNStatus, Bool) -> Void) {
        NETunnelProviderManager.loadAllFromPreferences { managers, error in
            if let error = error {
                NSLog("ERROR [Status]: \(error.localizedDescription)")
                completionHandler(.invalid, false)
                return
            }

            // If no managers exist, the extension hasn't been approved/configured yet
            guard let manager = managers?.first else {
                completionHandler(.invalid, false)
                return
            }

            // A manager can exist in preferences even when the network extension
            // is disabled in Login Items & Extensions. Check that the manager has
            // a valid protocol configuration with our bundle identifier to confirm
            // the extension is actually functional.
            guard let proto = manager.protocolConfiguration as? NETunnelProviderProtocol,
                  proto.providerBundleIdentifier == self.extensionBundleIdentifier,
                  manager.isEnabled else {
                NSLog("STATUS [Status]: Manager exists but extension is not enabled (isEnabled=\(manager.isEnabled))")
                completionHandler(.invalid, false)
                return
            }

            completionHandler(manager.connection.status, true)
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

extension VPNController: OSSystemExtensionRequestDelegate {
    func request(_ request: OSSystemExtensionRequest, actionForReplacingExtension existing: OSSystemExtensionProperties, withExtension extension: OSSystemExtensionProperties) -> OSSystemExtensionRequest.ReplacementAction {
        NSLog("Sysex: Replacing existing extension")
        return .replace
    }
    
    func requestNeedsUserApproval(_ request: OSSystemExtensionRequest) {
        NSLog("Sysex: Needs user approval")
    }
    
    func request(_ request: OSSystemExtensionRequest, didFinishWithResult result: OSSystemExtensionRequest.Result) {
        NSLog("Sysex: Finished with result \(result.rawValue)")
        isOperationInProgress = false
        activationCompletion?(true)
    }
    
    func request(_ request: OSSystemExtensionRequest, didFailWithError error: Error) {
        NSLog("Sysex: Failed with error \(error.localizedDescription)")
        isOperationInProgress = false
        activationCompletion?(false)
    }
}

// MARK: - Main Entry Point
let arguments = CommandLine.arguments
guard arguments.count > 1 else {
    print("Usage: resistine-vpn <command> [args]")
    print("Commands: activate, start <config_path>, stop, status")
    exit(1)
}

let command = arguments[1]
var commandCompleted = false

// Set up a timeout to exit if command takes too long
Timer.scheduledTimer(withTimeInterval: 30.0, repeats: false) { _ in
    if !commandCompleted {
        NSLog("Command timed out after 30 seconds")
        exit(1)
    }
}

func completeCommand() {
    commandCompleted = true
    exit(0)
}

switch command {
case "activate":
    VPNController.shared.activate { success in
        print(success ? "Activation request submitted" : "Activation request failed")
        if success {
            exit(0)
        } else {
            exit(1)
        }
    }

case "start":
    guard arguments.count > 2 else {
        print("Error: Missing config path for start command")
        exit(1)
    }
    let configPath = arguments[2]
    guard let configData = FileManager.default.contents(atPath: configPath),
          let configContents = String(data: configData, encoding: .utf8) else {
        print("Error: Could not read config file at \(configPath)")
        exit(1)
    }
    
    VPNController.shared.start(config: configContents) { success in
        print(success ? "VPN started successfully" : "Failed to start VPN")
        completeCommand()
    }

case "stop":
    VPNController.shared.stop { success in
        print(success ? "VPN stopped successfully" : "Failed to stop VPN")
        completeCommand()
    }

case "status":
    VPNController.shared.status { status, hasManager in
        if !hasManager {
            print("NotInstalled")
        } else {
            switch status {
            case .connected:
                print("Connected")
            case .connecting, .reasserting:
                print("Connecting")
            default:
                print("Disconnected")
            }
        }
        completeCommand()
    }

default:
    print("Unknown command: \(command)")
    exit(1)
}

// Run the main run loop to process XPC callbacks from NetworkExtension framework
RunLoop.main.run()

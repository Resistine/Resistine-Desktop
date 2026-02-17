import Foundation
import NetworkExtension

class XPCClient {
    static let shared = XPCClient()
    
    private var connection: NSXPCConnection?
    
    private init() {
        setupConnection()
    }
    
    private func setupConnection() {
        let connection = NSXPCConnection(serviceName: "com.resistine.desktop.vpnxpc")
        connection.remoteObjectInterface = NSXPCInterface(with: VPNXPCProtocol.self)
        
        connection.interruptionHandler = { [weak self] in
            NSLog("XPCClient: Connection interrupted. Reconnecting...")
            self?.setupConnection()
        }
        
        connection.invalidationHandler = {
            NSLog("XPCClient: Connection invalidated.")
            // Don't auto-reconnect on invalidation to avoid loops if the service is gone
        }
        
        connection.resume()
        self.connection = connection
        NSLog("XPCClient: Connection established")
    }
    
    func getProxy() -> VPNXPCProtocol? {
        return connection?.remoteObjectProxyWithErrorHandler { error in
            NSLog("XPCClient Error: \(error.localizedDescription)")
        } as? VPNXPCProtocol
    }
    
    func startVPN(config: String, completion: @escaping (Bool) -> Void) {
        getProxy()?.startVPN(config: config, with: completion)
    }
    
    func stopVPN(completion: @escaping (Bool) -> Void) {
        getProxy()?.stopVPN(with: completion)
    }
    
    func status(completion: @escaping (NEVPNStatus) -> Void) {
        getProxy()?.status { statusRaw in
            let status = NEVPNStatus(rawValue: statusRaw) ?? .invalid
            completion(status)
        }
    }
}

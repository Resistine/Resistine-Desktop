import Foundation

@objc protocol VPNXPCProtocol {
    func startVPN(config: String, with reply: @escaping (Bool) -> Void)
    func stopVPN(with reply: @escaping (Bool) -> Void)
    func status(with reply: @escaping (Int) -> Void)
}

let connection = NSXPCConnection(serviceName: "com.resistine.desktop.vpnxpc")
connection.remoteObjectInterface = NSXPCInterface(with: VPNXPCProtocol.self)
connection.resume()

guard let proxy = connection.remoteObjectProxyWithErrorHandler({ error in
    print("Error: \(error.localizedDescription)")
    exit(1)
}) as? VPNXPCProtocol else {
    print("Error: Could not create XPC proxy")
    exit(1)
}

let arguments = CommandLine.arguments
guard arguments.count > 1 else {
    print("Usage: resistine-vpn <command> [args]")
    print("Commands: start <config>, stop, status")
    exit(1)
}

let command = arguments[1]
let group = DispatchGroup()
group.enter()

switch command {
case "start":
    guard arguments.count > 2 else {
        print("Error: Missing config path for start command")
        exit(1)
    }
    let configPath = arguments[2]
    // Read the config file contents — the XPC service expects the WireGuard
    // config text, not a file path.
    guard let configData = FileManager.default.contents(atPath: configPath),
          let configContents = String(data: configData, encoding: .utf8) else {
        print("Error: Could not read config file at \(configPath)")
        exit(1)
    }
    proxy.startVPN(config: configContents) { success in
        print(success ? "VPN started successfully" : "Failed to start VPN")
        group.leave()
    }
case "stop":
    proxy.stopVPN { success in
        print(success ? "VPN stopped successfully" : "Failed to stop VPN")
        group.leave()
    }
case "status":
    proxy.status { statusRaw in
        // NEVPNStatus raw values: 0=invalid, 1=disconnected, 2=connecting,
        // 3=connected, 4=disconnecting, 5=reasserting
        switch statusRaw {
        case 3:
            print("Connected")
        case 2, 5:
            print("Connecting")
        default:
            print("Disconnected")
        }
        group.leave()
    }
default:
    print("Unknown command: \(command)")
    exit(1)
}

_ = group.wait(timeout: .now() + 10)
connection.invalidate()

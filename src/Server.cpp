#include "Server.h"

#include <iostream>
#include <string>
#include <cstring>

#include <sys/socket.h>
#include <netinet/in.h>
#include <unistd.h>

Server::Server(int portNumber)
    : port(portNumber),
      log("../data/kv.log")
{
    log.load(store);
}

void Server::start()
{
    int serverSocket = socket(AF_INET, SOCK_STREAM, 0);

    if (serverSocket == -1)
    {
        std::cout << "ERROR: Failed to create socket." << std::endl;
        return;
    }

    int option = 1;
    setsockopt(serverSocket, SOL_SOCKET, SO_REUSEADDR, &option, sizeof(&option));

    sockaddr_in serverAddress;
    std::memset(&serverAddress, 0, sizeof(serverAddress));

    serverAddress.sin_family = AF_INET;
    serverAddress.sin_addr.s_addr = INADDR_ANY;
    serverAddress.sin_port = htons(port);

    int bindResult = bind(serverSocket, reinterpret_cast<sockaddr*>(&serverAddress), sizeof(serverAddress));

    if (bindResult == -1)
    {
        std::cout << "ERROR: Failed to bind socket to port." << std::endl;
        close(serverSocket);
        return;
    }

    int listenResult = listen(serverSocket, 10);

    std::cout << "KV server listening on port " << port << "..." << std::endl;

    while (true)
    {
        sockaddr_in clientAddress;
        socklen_t clientAddressSize = sizeof(clientAddress);

        int clientSocket = accept(serverSocket, reinterpret_cast<sockaddr*>(&serverAddress), &clientAddressSize);

        if (clientSocket == -1)
        {
            std::cout << "ERROR: Failed to accept client." << std::endl; 
            continue;
        }

        handleClient(clientSocket);

        close(clientSocket);
    }

    close(serverSocket);
}

void Server::handleClient(int clientSocket)
{
    while (true)
    {    char buffer[1024];

        std::memset(buffer, 0, sizeof(buffer));

        ssize_t bytesRead = read(clientSocket, buffer, sizeof(buffer) - 1);

        if (bytesRead <= 0)
        {
            return;
        }

        std::string request(buffer);
        std::string response = processCommand(request);

        send(clientSocket, response.c_str(), response.size(), 0);
    }
}

std::string Server::processCommand(const std::string &line)
{
    Command command = parser.parse(line);

    if (command.type == CommandType::Put)
    {
        store.put(command.key, command.value);
        log.appendPut(command.key, command.value);
        return "OK\n";
    }
    else if (command.type == CommandType::Get)
    {
        std::string value;
        bool found = store.get(command.key, value);

        if (found)
        {
            return "VALUE " + value + "\n";
        }
        else
        {
            return "NOT_FOUND\n";
        }
    }
    else if (command.type == CommandType::Delete)
    {
        bool removed = store.remove(command.key);
        log.appendDelete(command.key);

        if (removed)
        {
            return "OK\n";
        }
        else
        {
        return "NOT_FOUND\n";
        }
    }

    return "ERROR invalid command\n";
   
}

#include "Server.h"

#include <thread>
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

    if (listenResult == -1)
    {
        std::cout << "ERROR: Failed to listen on socket." << std::endl;
        close(serverSocket);
        return;
    }

    std::cout << "KV server listening on port " << port << "..." << std::endl;

    while (true)
    {
        sockaddr_in clientAddress;
        socklen_t clientAddressSize = sizeof(clientAddress);

        int clientSocket = accept(serverSocket, reinterpret_cast<sockaddr*>(&clientAddress), &clientAddressSize);

        if (clientSocket == -1)
        {
            std::cout << "ERROR: Failed to accept client." << std::endl; 
            continue;
        }

        std::thread clientThread(
            &Server::handleClient,
            this,
            clientSocket
        );
        
        clientThread.detach();
    }

    close(serverSocket);
}

void Server::handleClient(int clientSocket)
{
    while (true)
    {
        char buffer[1024];

        std::memset(buffer, 0, sizeof(buffer));

        ssize_t bytesRead = read(clientSocket, buffer, sizeof(buffer) - 1);

        if (bytesRead <= 0)
        {
            break;
        }

        std::string request(buffer);

        bool shouldClose = false;
        std::string response = processCommand(request, shouldClose);

        send(clientSocket, response.c_str(), response.size(), 0);

        if (shouldClose)
        {
            break;
        }
    }

    close(clientSocket);
}

std::string Server::processCommand(const std::string &line, bool &shouldClose)
{
    shouldClose = false;
    Command command = parser.parse(line);

    if (command.type == CommandType::Exit)
    {
        shouldClose = true;
        return "GOODBYE\n";
    }

    if (command.type == CommandType::Put)
    {
        bool persisted = false;

        {
            std::lock_guard<std::mutex> lock(dataMutex);

            persisted = log.appendPut(command.key, command.value);

            if (persisted)
            {
                store.put(command.key, command.value);
            }
        }

        if (!persisted)
        {
            return "ERROR persistence failure\n";
        }

        return "OK\n";
    }
    else if (command.type == CommandType::Get)
    {
        std::string value;
        bool found = false;
        
        {
            std::lock_guard<std::mutex> lock(dataMutex);
            found = store.get(command.key, value);
        }

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
        bool found = false;
        bool persisted = false;

        {
            std::lock_guard<std::mutex> lock(dataMutex);

            std::string value;
            found = store.get(command.key, value);

            if (found)
            {
                persisted = log.appendDelete(command.key);

                if (persisted)
                {
                    store.remove(command.key);
                }
            }
        }

        if (!found)
        {
            return "NOT_FOUND\n";
        }

        if (!persisted)
        {
            return "ERROR persistence failure\n";
        }

        return "OK\n";
    }
    else if (command.type == CommandType::Compact)
    {
        bool compacted = false;

        {
            std::lock_guard<std::mutex> lock(dataMutex);
            std::unordered_map<std::string, std::string> entries = store.snapshot();
            compacted = log.compact(entries);
        }

        if (!compacted)
        {
            return "ERROR compaction failed\n";
        }

        return "OK\n";
    }

    return "ERROR invalid command\n";
   
}

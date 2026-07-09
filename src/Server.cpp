#include "Server.h"

#include <iostream>
#include <string>
#include <cstring>

#include <sys/socket.h>
#include <netinet/in.h>
#include <unistd.h>

Server::Server(int portNumber)
{
    port = portNumber;
}

void Server::start()
{

}

void Server::handleClient(int clientSocket)
{
    char buffer[1024];

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

std::string Server::processCommand(const std::string &line)
{
    Command command = parser.parse(line);

    if (command.type == CommandType::Put)
    {
        store.put(command.key, command.value);
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



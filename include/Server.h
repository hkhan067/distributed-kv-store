#pragma once

#include "KeyValueStore.h"
#include "CommandParser.h"

class Server
{
private:
    int port;
    KeyValueStore store;
    CommandParser parser;

    void handleClient(int clientSocket);
    std::string processCommand(const std::string &line);
public:
    Server(int portNumber);
    void start();
};
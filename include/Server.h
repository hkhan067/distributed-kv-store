#pragma once

#include "KeyValueStore.h"
#include "CommandParser.h"
#include "PersistenceLog.h"

#include <mutex>

class Server
{
private:
    int port;
    
    KeyValueStore store;
    CommandParser parser;
    PersistenceLog log;

    std::mutex dataMutex;

    void handleClient(int clientSocket);
    std::string processCommand(const std::string &line, bool &shouldClose);
public:
    Server(int portNumber);
    void start();
};

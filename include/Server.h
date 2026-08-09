#pragma once

#include "KeyValueStore.h"
#include "CommandParser.h"
#include "PersistenceLog.h"

#include <mutex>
#include <string>

class Server
{
private:
    int port;
    
    KeyValueStore store;
    CommandParser parser;
    PersistenceLog log;

    std::mutex dataMutex;

    void handleClient(int clientSocket);
    bool sendResponse(int clientSocket, const std::string &response);
    std::string processCommand(const std::string &line, bool &shouldClose);
public:
    Server(int portNumber, const std::string &logPath);
    bool start();
};

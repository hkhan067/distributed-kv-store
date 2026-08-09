#include "Server.h"

#include <iostream>
#include <string>

namespace
{
bool parsePort(const std::string &text, int &port)
{
    try
    {
        std::size_t parsedCharacters = 0;
        int parsedPort = std::stoi(text, &parsedCharacters);

        if (parsedCharacters != text.size() || parsedPort < 1 || parsedPort > 65535)
        {
            return false;
        }

        port = parsedPort;
        return true;
    }
    catch (const std::exception &)
    {
        return false;
    }
}

void printUsage(const char *programName)
{
    std::cerr << "Usage: " << programName << " [port log-path]" << std::endl;
}
}

int main(int argc, char *argv[])
{
    int port = 8080;
    std::string logPath = "../data/kv.log";

    if (argc != 1 && argc != 3)
    {
        printUsage(argv[0]);
        return 1;
    }

    if (argc == 3)
    {
        if (!parsePort(argv[1], port))
        {
            std::cerr << "ERROR: Port must be an integer from 1 to 65535." << std::endl;
            return 1;
        }

        logPath = argv[2];

        if (logPath.empty())
        {
            std::cerr << "ERROR: Log path cannot be empty." << std::endl;
            return 1;
        }
    }

    std::cout << "Persistence log: " << logPath << std::endl;

    Server server(port, logPath);

    return server.start() ? 0 : 1;
}

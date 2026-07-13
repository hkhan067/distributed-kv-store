#include "PersistenceLog.h"

#include <iostream>
#include <fstream>
#include <sstream>

PersistenceLog::PersistenceLog(const std::string &path)
    : filePath(path)
{
    
}

void PersistenceLog::appendPut(const std::string &key, const std::string &value)
{
    std::ofstream file(filePath, std::ios::app);

    if (!file)
    {
        std::cout << "ERROR: Failed to open persistence log." << std::endl;
        return;
    }

    file << "PUT " << key << " " << value << "\n";
}

void PersistenceLog::appendDelete(const std::string &key)
{
    std::ofstream file(filePath, std::ios::app);

    if (!file)
    {
        std::cout << "ERROR: Failed to open persistence log." << std::endl;
        return;
    }

    file << "DELETE " << key << "\n";
}

void PersistenceLog::load(KeyValueStore &store)
{
    std::ifstream file(filePath);

    if (!file)
    {
        return;
    }

    std::string line = "";

    while (std::getline(file, line))
    {
        std::stringstream ss(line);

        std::string command = "";
        std::string key     = "";
        std::string value   = "";

        ss >> command;
        ss >> key;
        ss >> value;

        if (command == "PUT")
        {
            store.put(key, value);
        }
        else if (command == "DELETE")
        {
            store.remove(key);
        }
    }

}

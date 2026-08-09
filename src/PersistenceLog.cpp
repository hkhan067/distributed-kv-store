#include "PersistenceLog.h"

#include <cstdio>
#include <fcntl.h>
#include <fstream>
#include <sstream>
#include <unistd.h>

PersistenceLog::PersistenceLog(const std::string &path)
    : filePath(path)
{

}

bool PersistenceLog::syncFile(const std::string &path) const
{
    int fileDescriptor = open(path.c_str(), O_RDONLY);

    if (fileDescriptor == -1)
    {
        return false;
    }

    bool synced = fsync(fileDescriptor) == 0;
    close(fileDescriptor);

    return synced;
}

bool PersistenceLog::append(const std::string &entry)
{
    std::ofstream file(filePath, std::ios::app);

    if (!file)
    {
        return false;
    }

    file << entry << "\n";
    file.flush();

    if (!file)
    {
        return false;
    }

    file.close();

    if (file.fail())
    {
        return false;
    }

    return syncFile(filePath);
}

bool PersistenceLog::appendPut(const std::string &key, const std::string &value)
{
    return append("PUT " + key + " " + value);
}

bool PersistenceLog::appendDelete(const std::string &key)
{
    return append("DELETE " + key);
}

bool PersistenceLog::compact(
    const std::unordered_map<std::string, std::string> &entries
)
{
    std::string temporaryPath = filePath + ".tmp";
    std::ofstream temporaryFile(temporaryPath, std::ios::trunc);

    if (!temporaryFile)
    {
        return false;
    }

    for (const std::pair<const std::string, std::string> &entry : entries)
    {
        temporaryFile << "PUT " << entry.first << " " << entry.second << "\n";
    }

    temporaryFile.flush();

    if (!temporaryFile)
    {
        temporaryFile.close();
        std::remove(temporaryPath.c_str());
        return false;
    }

    temporaryFile.close();

    if (temporaryFile.fail() || !syncFile(temporaryPath))
    {
        std::remove(temporaryPath.c_str());
        return false;
    }

    if (std::rename(temporaryPath.c_str(), filePath.c_str()) != 0)
    {
        std::remove(temporaryPath.c_str());
        return false;
    }

    return syncFile(filePath);
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
        std::string key = "";
        std::string value = "";

        ss >> command;
        ss >> key;
        ss >> value;

        if (command == "PUT" && !key.empty() && !value.empty())
        {
            store.put(key, value);
        }
        else if (command == "DELETE" && !key.empty())
        {
            store.remove(key);
        }
    }
}

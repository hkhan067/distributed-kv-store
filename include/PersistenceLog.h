#pragma once

#include <KeyValueStore.h>

#include <string>
#include <unordered_map>

class PersistenceLog
{
private:
    std::string filePath;

    bool append(const std::string &entry);
    bool syncFile(const std::string &path) const;
public:
    PersistenceLog(const std::string &path);

    bool appendPut(const std::string &key, const std::string &value);
    bool appendDelete(const std::string &key);
    bool compact(const std::unordered_map<std::string, std::string> &entries);

    void load(KeyValueStore &store);
};

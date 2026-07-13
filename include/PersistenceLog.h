#pragma once

#include <KeyValueStore.h>

#include <string>

class PersistenceLog
{
private:
    std::string filePath;
public:
    PersistenceLog(const std::string &path);

    void appendPut(const std::string &key, const std::string &value);
    void appendDelete(const std::string &key);

    void load(KeyValueStore &store);
};
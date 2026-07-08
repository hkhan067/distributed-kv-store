#pragma once

#include <string>
#include <sstream>

enum class CommandType
{
    Put,
    Get,
    Delete,
    Invalid,
    Exit
};

struct Command
{
    CommandType type;
    std::string key;
    std::string value;
};

class CommandParser
{
public:
    Command parse(const std::string &line) const;
};
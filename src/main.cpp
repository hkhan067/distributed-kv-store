#include "CommandParser.h"
#include "KeyValueStore.h"

#include <iostream>

int main()
{
    KeyValueStore store;
    CommandParser parser;

    std::cout << "Distributed KV Store - Level 1" << std::endl;
    std::cout << "Commands: PUT key value, GET key, DELETE key, EXIT" << std::endl;

    std::string line = "";

    while (true)
    {
        std::cout << "> ";
        std::getline(std::cin, line);

        Command command = parser.parse(line);
        if (command.type == CommandType::Put)
        {
            store.put(command.key, command.value);
            std::cout << "OK" << std::endl;
        }
        else if (command.type == CommandType::Get)
        {
            std::string value;
            bool found = store.get(command.key, value);

            if (found)
            {
                std::cout << "VALUE " << value << std::endl; 
            }
            else
            {
                std::cout << "NOT_FOUND" << std::endl;
            }
        }
        else if (command.type == CommandType::Delete)
        {
            bool removed = store.remove(command.key);

            if (removed)
            {
                std::cout << "OK" << std::endl;
            }
            else
            {
                std::cout << "NOT_FOUND" << std::endl;
            }
        }
        else if (command.type == CommandType::Exit)
        {
            std::cout << "Goodbye." << std::endl;
            break;
        }
        else
        {
            std::cout << "ERROR invalid command" << std::endl;
        }
    }

    return 0;
}
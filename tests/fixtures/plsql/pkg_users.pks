CREATE OR REPLACE PACKAGE pkg_users AS

    PROCEDURE create_user(
        p_name     IN VARCHAR2,
        p_email    IN VARCHAR2,
        p_user_id  OUT NUMBER
    );

    FUNCTION get_user_by_id(
        p_user_id IN NUMBER
    ) RETURN VARCHAR2;

    PROCEDURE update_user_status(
        p_user_id IN NUMBER,
        p_status  IN VARCHAR2
    );

END pkg_users;

# Email Validation Toolkit

The Email Validation Toolkit is a web application designed to help users validate email addresses from a CSV file. It performs various checks to ensure that the email addresses are valid, including syntax validation, domain existence, SMTP server response, and checks against disposable and role-based email domains. This toolkit is particularly useful for businesses and organizations that need to maintain a clean and valid email list for communication purposes.

## Features

### CSV File Upload
Users can upload CSV files containing email addresses for validation.

### Email Validation Checks
- **Syntax Validity:** Checks if the email address follows the correct format.
- **Domain Validity:** Verifies if the domain of the email address exists.
- **SMTP Validity:** Checks if the email address can receive emails by querying the SMTP server.
- **Disposable Email Check:** Identifies if the email address belongs to a disposable email service.
- **Role-Based Email Check:** Detects if the email address is a role-based account (e.g., admin, support).

### Progress Tracking
Users can see the progress of the validation process in real-time.

### Download Results
After validation, users can download a CSV file containing the results of the validation checks.

## Technologies Used

### Backend
- **Flask:** A lightweight WSGI web application framework for Python.

### Frontend
- **HTML:** For structuring the web pages.
- **CSS:** For styling the application.
- **JavaScript:** For client-side scripting and handling user interactions.

### Libraries
- **PapaParse:** A powerful CSV parser for JavaScript that allows easy parsing of CSV files.
- **dnspython:** A DNS toolkit for Python that allows querying DNS records.
- **Werkzeug:** A comprehensive WSGI web application library that provides utilities for secure file handling.

## Installation

To set up the Email Validation Toolkit on your local machine, follow these steps:

### Clone the Repository
```bash
git clone <>
cd EmailValid
```

### Install Required Packages
Make sure you have Python and pip installed. Then, run the following command to install the necessary dependencies:
```bash
pip install -r requirements.txt
```

### Run the Application
Start the Flask application by executing:
```bash
python app.py
```

### Access the Application
Open your web browser and navigate to `http://localhost:5000` to access the Email Validation Toolkit.

## Usage

### Upload CSV File
- Click on the "Choose CSV File" button to upload a CSV file containing email addresses.
- The file should be in a standard CSV format.

### Specify CSV Options
- Indicate whether the CSV file contains a header row by checking the "CSV contains header row" checkbox.
- Select the column that contains the email addresses from the dropdown menu.

### Start Validation
- Click the "Start Validation" button to begin the validation process.
- A progress bar will display the status of the validation.

### Download Results
- Once the validation is complete, a download link will appear.
- Click on the "Download Results" button to download a CSV file containing the validation results.

## Validation Results
The downloaded CSV file will contain the following columns:

| Column           | Description                                                 |
|-----------------|-------------------------------------------------------------|
| **Email**       | The email address that was validated.                      |
| **Valid Syntax** | Indicates whether the email address has valid syntax (True/False). |
| **Valid Domain** | Indicates whether the domain of the email address exists (True/False). |
| **SMTP Valid**  | Indicates whether the email address can receive emails (True/False). |
| **Disposable**  | Indicates whether the email address is from a disposable email service (True/False). |
| **Role Account** | Indicates whether the email address is a role-based account (True/False). |
| **Catch-All Domain** | Indicates whether the domain is a catch-all domain (True/False). |
| **Errors**      | Any errors encountered during validation.                   |

## Contributing

Contributions to the Email Validation Toolkit are welcome! If you would like to contribute, please follow these steps:

1. Fork the repository.
2. Create a new branch for your feature or bug fix.
3. Make your changes and commit them.
4. Push your changes to your forked repository.
5. Submit a pull request detailing your changes.

## License

This project is licensed under the MIT License. See the LICENSE file for more details.

## Contact

For any inquiries or issues, please contact the project maintainer at [basumgarianand109@gmail.com].

## Acknowledgments

Special thanks to the contributors and libraries that made this project possible. This toolkit is built with the intention of helping users maintain a clean and valid email list for effective communication.

**Note:** Ensure that you have Python and pip installed on your machine before running the application.


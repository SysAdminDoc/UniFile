How to add a custom classifier
==============================

Use :class:`unifile_sdk.Classifier` as the conservative baseline, then layer
application-specific rules around it. The base classifier remains available
for names your rule does not recognize::

   from unifile_sdk import Classifier


   class ProjectClassifier(Classifier):
       def classify(self, folder_name, folder_path=None):
           normalized = folder_name.casefold()
           if "client-acme" in normalized:
               return {
                   "category": "Client Work",
                   "confidence": 100,
                   "cleaned_name": folder_name,
                   "method": "custom",
                   "detail": "Project-specific client rule",
                   "metadata": {},
                   "topic": None,
               }
           return super().classify(folder_name, folder_path)


   result = ProjectClassifier().classify("client-acme-q3")

Keep custom rules deterministic and review-first. Return the same result keys
as the base classifier so callers can display confidence and method details
consistently. A ``log_callback`` can be passed to the base constructor when
the host wants human-readable pipeline messages.

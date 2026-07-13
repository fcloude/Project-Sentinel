class AIInterface(ABC):

    @abstractmethod
    def detect(self, frame):
        pass